# simcore_ai_django/codecs/base.py
from __future__ import annotations

from typing import Any, Optional, Mapping

import base64
import json

from django.db import transaction

from pydantic import BaseModel, ValidationError

from simcore_ai.codecs import BaseLLMCodec
from simcore_ai.codecs.exceptions import CodecDecodeError
from simcore_ai.types import LLMResponse, LLMTextPart, LLMToolResultPart
from simcore_ai.tracing import service_span_sync
from simcore_ai_django.signals import emitter


class DjangoBaseLLMCodec(BaseLLMCodec):
    """
    Django-aware codec base.

    Pipeline (sync):
      1) `validate_from_response(resp)`  → optional schema validation/parsing
      2) `restructure(candidate, resp)`  → normalize/coerce into app model (default: Pydantic model)
      3) `persist_atomic(resp=resp, structured=..., **ctx)` → apps override to write ORM records (atomic)
      4) `emit(result=result, resp=resp, **ctx)` → optional post-commit signals/outbox/websockets

    Key principles:
      - This base stays free of direct ORM models; apps provide them via **ctx.
      - Validation errors raise `CodecDecodeError` and should be caught by the service/UI.
      - Idempotency is recommended inside `persist()` (e.g., unique by `(namespace, bucket, name, correlation_id)`).
      - Emission should run **after commit** via `transaction.on_commit`.

    Usage:
      class PatientInitialResponseCodec(DjangoBaseLLMCodec):
          response_format_class = PatientInitialOutputSchema  # optional

          def persist(self, *, resp: LLMResponse, structured: Any | None = None, **ctx) -> Any:
              # Implement idempotent writes using resp.identity + resp.correlation_id
              ...

      # In a service handler:
      codec = PatientInitialResponseCodec()
      result = codec.handle_response(resp, context={"simulation_pk": sim.pk})

    Signals:
      Apps should connect to the emitter signals and filter by identity:

      @receiver(ai_response_ready)
      def on_ready(sender, **payload):
          if (payload.get("namespace"), payload.get("bucket")) != ("chatlab", "sim_responses"):
              return
          ...
    """

    # Hints for the base implementation (subclasses may override)
    response_format_class: type[BaseModel] | None = None
    # Only attempt text→JSON extraction when a response_format_class is present unless this flag is True
    allow_text_json_without_schema: bool = False

    # --- main entrypoints -------------------------------------------------
    def validate_from_response(self, resp: LLMResponse) -> BaseModel | None:
        """
        Best-effort extractor + validator.

        Returns:
            - A Pydantic model instance if a structured candidate is found AND validated
            - None if no candidate is found OR no response_format_class is set
        Raises:
            - CodecDecodeError if validation against `response_format_class` fails
        """
        with service_span_sync(
            "ai.codec.validate",
            attributes={
                "ai.codec": self.__class__.__name__,
                "ai.schema": getattr(getattr(self, "response_format_class", None), "__name__", None),
            },
        ):
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None

            schema_cls = getattr(self, "response_format_class", None)
            if schema_cls is None:
                # Structured candidate exists but no schema to validate against
                return None

            try:
                return schema_cls.model_validate(candidate)  # type: ignore[attr-defined]
            except ValidationError as ve:
                # Bubble up as CodecDecodeError; service span handles error status
                raise CodecDecodeError(f"Response failed schema validation: {ve}") from ve

    def restructure(self, candidate: Mapping[str, Any] | None, resp: LLMResponse) -> Any:
        """
        Normalize/coerce the extracted candidate into the final structured object.

        Default behavior:
          - If `response_format_class` is set and candidate is not None:
              return response_format_class.model_validate(candidate)
          - Else:
              return candidate (unchanged)

        Subclasses can override to merge tool outputs, coerce datatypes, or enrich data.
        """
        schema_cls = getattr(self, "response_format_class", None)
        if candidate is None:
            return None
        if schema_cls is not None:
            return schema_cls.model_validate(candidate)  # type: ignore[attr-defined]
        return candidate

    def persist(self, *, resp: LLMResponse, structured: Any | None = None, **ctx: Any) -> Any:  # pragma: no cover - abstract by convention
        """Apps MUST override: write ORM records based on resp, structured object, and ctx.

        Return an app-specific result (e.g., a model instance or PK).

        Recommended idempotency key: (resp.namespace, resp.bucket, resp.name, resp.correlation_id).
        Handle IntegrityError by re-fetching and returning the existing row.
        """
        raise NotImplementedError

    def persist_atomic(self, *, resp: LLMResponse, structured: Any | None = None, **ctx: Any) -> Any:
        """Atomic wrapper for persist(). Useful for idempotent writes."""
        with service_span_sync("ai.codec.persist", attributes={"ai.codec": self.__class__.__name__}):
            with transaction.atomic():
                return self.persist(resp=resp, structured=structured, **ctx)

    def emit(self, *, result: Any, resp: LLMResponse, **ctx: Any) -> None:  # pragma: no cover - optional
        """
        Default emission uses the Django signals emitter after commit.
        Payload is intentionally small and ID-based to avoid tight coupling.
        """
        with service_span_sync("ai.codec.emit", attributes={"ai.codec": self.__class__.__name__}):
            def _send():
                payload = {
                    "namespace": getattr(resp, "namespace", None),
                    "bucket": getattr(resp, "bucket", None),
                    "name": getattr(resp, "name", None),
                    "correlation_id": getattr(resp, "correlation_id", None),
                    "request_correlation_id": getattr(resp, "request_correlation_id", None),
                    "provider": getattr(resp, "provider_name", None),
                    "client": getattr(resp, "client_name", None),
                    # Optional DB context from ctx/result
                    "simulation_pk": ctx.get("simulation_pk") if isinstance(ctx, dict) else None,
                    "response_db_pk": getattr(result, "pk", None) if result is not None else None,
                }
                emitter.response_ready(payload)

            # ensure emission only fires if the transaction commits
            transaction.on_commit(_send)

    # Convenience orchestration for codecs --------------------------------
    def handle_response(self, resp: LLMResponse, *, context: Optional[dict[str, Any]] = None) -> Any:
        """Full codec pipeline: extract/validate → restructure → persist (atomic) → emit.

        Returns the value from `persist_atomic` (often a model instance or PK).
        """
        ctx = context or {}
        with service_span_sync(
            "ai.codec.handle",
            attributes={
                "ai.codec": self.__class__.__name__,
                "ai.identity.codec": ".".join(
                    str(x)
                    for x in (
                        getattr(resp, "namespace", None),
                        getattr(resp, "bucket", None),
                        getattr(resp, "name", None),
                    )
                    if x
                ),
                "ai.corr.request": getattr(resp, "request_correlation_id", None),
                "ai.corr.response": getattr(resp, "correlation_id", None),
                "ai.provider": getattr(resp, "provider_name", None),
                "ai.client": getattr(resp, "client_name", None),
                "ai.schema": getattr(getattr(self, "response_format_class", None), "__name__", None),
            },
        ):
            # 1) validate (optional)
            validated_model = self.validate_from_response(resp)

            # 2) restructure (even if validate returned None; restructure may still shape data)
            with service_span_sync(
                "ai.codec.restructure",
                attributes={
                    "ai.codec": self.__class__.__name__,
                    "ai.schema": getattr(getattr(self, "response_format_class", None), "__name__", None),
                },
            ):
                candidate_dict = None
                if validated_model is not None:
                    # if validated, convert to dict for downstream restructuring (some apps prefer dict)
                    try:
                        candidate_dict = validated_model.model_dump()  # type: ignore[attr-defined]
                    except Exception:
                        candidate_dict = validated_model  # fallback: pass through
                else:
                    candidate_dict = self.extract_structured_candidate(resp)
                structured = self.restructure(candidate_dict, resp)

            # 3) persist (atomic/idempotent)
            result = self.persist_atomic(resp=resp, structured=structured, **ctx)

            # 4) emit (post-commit)
            self.emit(result=result, resp=resp, **ctx)
            return result

    def extract_structured_candidate(self, resp: LLMResponse) -> Any:
        """
        Extract a structured candidate from the response in priority order:
          1) Provider-provided dict at resp.provider_meta["structured"]
          2) Tool result parts: JSON MIME/base64
          3) Text parts: JSON parse (guarded by response_format_class or allow_text_json_without_schema)
        """
        with service_span_sync(
            "ai.codec.extract",
            attributes={"ai.codec": self.__class__.__name__},
        ):
            # 1) Provider-provided (authoritative)
            try:
                obj = (getattr(resp, "provider_meta", {}) or {}).get("structured")
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

            # 2) Tool result → JSON
            try:
                for item in getattr(resp, "outputs", []) or []:
                    for part in getattr(item, "content", []) or []:
                        if isinstance(part, LLMToolResultPart) and (part.mime_type or "").startswith(
                            ("application/json", "text/json")
                        ):
                            try:
                                raw = base64.b64decode(part.data_b64).decode("utf-8")
                                return json.loads(raw)
                            except Exception:
                                continue
            except Exception:
                pass

            # 3) Text → JSON (guarded)
            try:
                if self.response_format_class is not None or self.allow_text_json_without_schema:
                    for item in getattr(resp, "outputs", []) or []:
                        for part in getattr(item, "content", []) or []:
                            if isinstance(part, LLMTextPart):
                                try:
                                    return json.loads(part.text)
                                except Exception:
                                    continue
            except Exception:
                pass

            return None