# simcore_ai/components/codecs/openai/responses_json.py
"""
OpenAI Responses JSON codec.

This codec is responsible for:
  - Taking a provider-agnostic response schema (Pydantic model class or JSON Schema dict)
    from the Request and adapting it for the OpenAI Responses API.
  - Producing the provider-specific JSON payload that will be sent via the `text` parameter.
  - Optionally validating structured output from a Response back into the declared schema.

It is intentionally OpenAI-specific but still registered in the global codecs registry,
keyed by identity (namespace='openai', kind='responses', name='json').
"""

from typing import Any, ClassVar, Sequence

from pydantic import ValidationError
from simcore_ai.components.codecs.base import BaseCodec
from simcore_ai.decorators.codec import codec

from simcore_ai.components.codecs.exceptions import CodecDecodeError, CodecSchemaError
from simcore_ai.providers.openai.schema_adapters import FlattenUnions
from simcore_ai.tracing import service_span_sync
from simcore_ai.types import Request, Response


class OpenAiNamespaceMixin:
    """Mixin for OpenAI codecs. Sets the codec namespace and provider name."""
    namespace: ClassVar[str] = "openai"
    provider_name: ClassVar[str] = "openai"


class OpenAIResponsesBaseCodec(OpenAINamespaceMixin, BaseCodec):
    """Base class for OpenAI Responses codecs."""
    kind: ClassVar[str] = "responses"


@codec(name="json")
class OpenAIResponsesJsonCodec(OpenAIResponsesBaseCodec):
    """Codec for OpenAI Responses JSON structured output.

    Encode:
      - Reads `Request.response_schema` (Pydantic model class) or `Request.response_schema_json` (dict).
      - Applies OpenAI-specific schema adapters (e.g., flattening oneOf unions).
      - Writes:
          * `Request.response_schema_json` for diagnostics.
          * `Request.provider_response_format` as the provider-specific payload that
            the OpenAI provider passes to the Responses API via the `text` parameter.

    Decode:
      - Extracts a structured candidate dict from the `Response` (provider_meta/JSON/tool result).
      - If the original `Request.response_schema` is present on `Response.request`, validates
        into that Pydantic model; otherwise returns the raw dict.
    """

    abstract: ClassVar[bool] = False

    # This codec is schema-agnostic at the class level; it relies on the Request
    # to provide the concrete Pydantic schema (Request.response_schema).
    output_schema_cls: ClassVar[type | None] = None

    # Ordered list of schema adapters to apply for OpenAI JSON.
    schema_adapters: ClassVar[Sequence[FlattenUnions]] = (FlattenUnions(),)

    async def aencode(self, req: Request) -> None:
        """Attach provider-specific response format for OpenAI Responses.

        Flow:
          - Determine base schema from `response_schema` (Pydantic) or `response_schema_json` (dict).
          - Run schema adapters to produce an OpenAI-friendly JSON Schema.
          - Store the adapted schema on `req.response_schema_json` for diagnostics.
          - Build the OpenAI JSON wrapper and assign it to `req.provider_response_format`.
        """
        with service_span_sync(
                "simcore.codec.encode",
                attributes={
                    "simcore.codec": self.__class__.__name__,
                    "simcore.provider_name": "openai",
                    "simcore.codec.kind": "responses.json",
                },
        ):
            base_schema: dict[str, Any] | None = None

            # Prefer the Pydantic model class if present.
            source = getattr(req, "response_schema", None)
            if source is not None:
                try:
                    base_schema = source.model_json_schema()
                except Exception as exc:
                    raise CodecSchemaError(
                        f"{self.__class__.__name__}: failed to build JSON schema "
                        f"from response_schema={source!r}"
                    ) from exc

            # Fallback: an explicit JSON Schema dict attached by the service.
            if base_schema is None:
                candidate = getattr(req, "response_schema_json", None)
                if candidate is None:
                    # No structured output requested; nothing to encode.
                    return
                if not isinstance(candidate, dict):
                    raise CodecSchemaError(
                        f"{self.__class__.__name__}: response_schema_json must be a dict, "
                        f"got {type(candidate).__name__}"
                    )
                base_schema = candidate

            # Apply schema adapters (OpenAI-specific quirks such as flattening oneOf).
            compiled = base_schema
            for adapter in self.schema_adapters:
                try:
                    compiled = adapter.adapt(compiled)
                except Exception as exc:  # pragma: no cover - defensive
                    raise CodecSchemaError(
                        f"{self.__class__.__name__}: schema adapter {type(adapter).__name__} failed"
                    ) from exc

            # Keep adapted schema for diagnostics
            req.response_schema_json = compiled

            # Build OpenAI JSON envelope for Responses API.
            meta = dict(self.output_schema_meta or {})
            name = meta.get("name") or "response"
            strict = bool(meta.get("strict", True))

            provider_payload: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": name,
                    "schema": compiled,
                    "strict": strict,
                },
            }
            setattr(req, "provider_response_format", provider_payload)

    async def adecode(self, resp: Response) -> Any | None:
        """Decode structured output from a Response into the declared schema, if available.

        - Extracts the best candidate dict via BaseCodec.extract_structured_candidate.
        - If `Response.request.response_schema` is present and looks like a Pydantic model
          class, validates the dict into that model.
        - If no schema is available, returns the raw dict.
        """
        with service_span_sync(
                "simcore.codec.decode",
                attributes={
                    "simcore.codec": self.__class__.__name__,
                    "simcore.provider_name": "openai",
                    "simcore.codec.kind": "responses.json",
                },
        ):
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None

            # Locate the original schema class, if any.
            schema_cls = None
            req = getattr(resp, "request", None)
            if req is not None:
                schema_cls = getattr(req, "response_schema", None)

            # No schema: return the raw dict (already normalized).
            if schema_cls is None:
                return candidate

            try:
                # Prefer Pydantic v2-style model_validate if available.
                mv = getattr(schema_cls, "model_validate", None)
                if callable(mv):
                    return mv(candidate)
                # Fallback: try constructing directly (best-effort).
                return schema_cls(**candidate)  # type: ignore[call-arg]
            except ValidationError as exc:
                raise CodecDecodeError(
                    f"{self.__class__.__name__}: validation failed for structured output"
                ) from exc
            except Exception as exc:  # pragma: no cover - defensive
                raise CodecDecodeError(
                    f"{self.__class__.__name__}: unexpected error during decode"
                ) from exc
