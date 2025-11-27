# simcore_ai/components/codec/base.py
import base64
import json
import logging
from abc import ABC
from typing import Any, ClassVar, Protocol

from asgiref.sync import async_to_sync
from pydantic import ValidationError

from .exceptions import CodecDecodeError, CodecSchemaError
from ..schemas.base import BaseOutputSchema
from ...components.base import BaseComponent
from ...identity import IdentityMixin
from ...tracing import service_span_sync
from ...types import Request, Response, StreamChunk
from ...types.output import OutputTextContent, OutputToolResultContent, OutputJsonContent

logger = logging.getLogger(__name__)


class SchemaAdapter(Protocol):
    """Contract for codec-local schema adapters that transform JSON Schema.

    Implementations receive a JSON-like dict and must return a dict.
    """

    def adapt(self, schema: dict[str, Any]) -> dict[str, Any]: ...


class BaseCodec(IdentityMixin, BaseComponent, ABC):
    """Provider-aware, per-call codec for structured output.

    Responsibilities
    ----------------
    • Advertise a Pydantic schema via `response_schema`.
    • During encode, set structured-output hints on the request:
        - response_schema (Pydantic model class)
        - response_schema_json (canonical JSON Schema dict)
        - provider_response_format (provider-native response_format payload)
    • During decode, validate normalized responses/stream chunks to that schema.
    • Never call provider SDKs directly; providers consume `provider_response_format`
      and normalize raw responses into `Response` DTOs that codecs then decode.
    """

    response_schema: ClassVar[type[BaseOutputSchema] | None] = None

    # Ordered list of schema adapters for this codec.
    # Provider-wide adapters live on codec base classes; result-type-specific adapters
    # can be appended in subclasses.
    schema_adapters: ClassVar[list[SchemaAdapter]] = []


    def __init__(self) -> None:
        super().__init__()
        self._stream_buffer: list[Any] | None = None

    def __init_subclass__(cls, **kw) -> None:  # pragma: no cover - light guardrails
        """Ensure IdentityMixin hooks run; registration is handled by decorators."""
        super().__init_subclass__(**kw)

    # ---- Selection helpers -------------------------------------------------
    @classmethod
    def matches(cls, *, provider: Any, api: str, result_type: str) -> bool:
        """Return True if this codec should be used for the given provider/api/result_type.

        Default implementation matches against the codec's Identity:

            namespace -> provider name
            kind      -> API label (e.g., "responses")
            name      -> result type (e.g., "json")

        Subclasses may override this for more advanced routing logic.
        """
        provider_name = getattr(provider, "name", None) or str(provider)
        ident = cls.identity
        return (
            ident.namespace == provider_name
            and ident.kind == api
            and ident.name == result_type
        )

    @classmethod
    def select_for(cls, *, provider: Any, api: str, result_type: str):
        """Return all registered codec classes that match this call signature.

        This is a thin helper over the codecs registry using a predicate that
        first pre-filters by provider namespace, then delegates to each codec's
        `matches` method. Services should use this as the primary entrypoint
        when orchestrating codec selection.
        """
        # Local import to avoid circular dependency at module import time.
        from ...registry.singletons import codecs as codec_registry

        provider_name = getattr(provider, "name", None) or str(provider)

        def _pred(candidate) -> bool:
            # Quick pre-filter by provider namespace to avoid unnecessary work.
            try:
                if candidate.identity.namespace != provider_name:
                    return False
            except Exception:
                return False
            return bool(
                getattr(candidate, "matches", None)
                and candidate.matches(provider=provider_name, api=api, result_type=result_type)
            )

        return codec_registry.filter(_pred)

    # ---- Lifecycle: setup/teardown are optional ----------------------------
    async def asetup(self, *, context: dict[str, Any] | None = None) -> None:
        self._stream_buffer = []

    async def ateardown(self, *, context: dict[str, Any] | None = None) -> None:
        self._stream_buffer = None

    # ---- Encode -----------------------------------------------------------
    async def aencode(self, req: Request) -> None:
        """Attach structured-output hints and provider response format to the request.

        Sets (when `response_schema` is defined):
          - req.response_schema           (Pydantic model class)
          - req.response_schema_json      (canonical JSON Schema dict)
          - req.provider_response_format  (provider-native payload)
        """
        cls = type(self)
        if cls.response_schema is None:
            # No schema configured; nothing to encode.
            logger.debug("%s: no structured output schema defined", cls.__name__)
            return

        with service_span_sync(
            "simcore.codec.encode",
            attributes={
                "simcore.codec": cls.__name__,
                "simcore.response_schema": getattr(cls.response_schema, "__name__", "<Not Set>"),
            },
        ):
            try:
                schema_cls = cls.response_schema

                # Attach schema class if not already provided by the service.
                if getattr(req, "response_schema", None) is None:
                    req.response_schema = schema_cls

                # Canonical JSON Schema from the Pydantic model.
                schema_json = schema_cls.model_json_schema()
                req.response_schema_json = schema_json

                # Provider-specific adaptation and envelope.
                adapted = self.adapt_schema(schema_json)
                provider_format = self._build_provider_response_format(adapted)
                req.provider_response_format = provider_format

            except Exception as e:  # pragma: no cover - defensive guard
                raise CodecSchemaError(
                    f"{cls.__name__}: failed to encode request hints for structured output"
                ) from e

    def encode(self, req: Request) -> None:
        return async_to_sync(self.aencode)(req)

    # ---- Schema adaptation -------------------------------------------------
    def adapt_schema(self, base_schema: dict[str, Any]) -> dict[str, Any]:
        """Run this codec's schema adapters in order.

        Provider-wide adapters should live on base codec classes (e.g., OpenAIBaseCodec),
        and result-type-specific adapters should be appended in concrete subclasses.
        """
        out = base_schema
        for adapter in type(self).schema_adapters:
            try:
                out = adapter.adapt(out)
            except Exception as exc:  # pragma: no cover - adapter bugs should surface clearly
                logger.exception("%s: schema adapter %r failed", type(self).__name__, adapter)
                raise CodecSchemaError(
                    f"{type(self).__name__}: schema adapter {adapter!r} failed"
                ) from exc
        return out

    def _build_provider_response_format(
        self,
        adapted_schema: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Provider-specific envelope for the adapted schema.

        Default implementation returns the adapted schema directly. Provider-specific
        codecs (e.g., OpenAI JSON) should override this to wrap the schema into the
        provider's `response_format` payload.
        """
        return adapted_schema or None

    # ---- Decode -----------------------------------------------------------
    async def adecode(self, resp: Response) -> BaseOutputSchema | None:
        """Extract and validate structured output from a non-stream response.

        Returns a validated model, or None if no structured payload exists.
        """
        cls = type(self)
        if cls.response_schema is None:
            return None
        with service_span_sync(
            "simcore.codec.decode",
            attributes={
                "simcore.codec": cls.__name__,
                "simcore.response_schema": getattr(cls.response_schema, "__name__", "<Not Set>"),
            },
        ):
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None
            return self.validate_dict(candidate)

    async def arun(self, resp: Response) -> BaseOutputSchema | None:  # deprecated path
        return await self.adecode(resp)

    # ---- Streaming hooks --------------------------------------------------
    async def adecode_chunk(
        self,
        chunk: StreamChunk,
        *,
        is_final: bool = False,
    ) -> tuple[BaseOutputSchema | None, bool]:
        """Consume a streaming chunk.

        Return (partial_model_or_None, done_bool). Default implementation
        accumulates nothing and never finishes early.
        """
        return None, False

    async def afinalize_stream(self) -> BaseOutputSchema | None:
        """Finalize accumulated streaming state into a validated model (or None).

        Default: no accumulation; return None.
        """
        return None

    # ---- Schema utilities -------------------------------------------------
    def json_schema(self) -> dict:
        if type(self).response_schema is None:
            raise CodecSchemaError(f"Codec '{self.__class__.__name__}' has no 'response_schema' defined")
        try:
            return type(self).response_schema.model_json_schema()
        except Exception as e:
            raise CodecSchemaError(
                f"Failed to build JSON schema for codec '{self.__class__.__name__}'"
            ) from e

    # ---- Validation --------------------------------------------------------
    def validate_dict(self, data: dict[str, Any]) -> BaseOutputSchema:
        if type(self).response_schema is None:
            raise CodecSchemaError(f"Codec '{self.__class__.__name__}' has no 'response_schema' defined")
        try:
            return type(self).response_schema.model_validate(data)
        except ValidationError as e:
            raise CodecDecodeError(
                f"Validation failed for codec '{self.__class__.__name__}'"
            ) from e

    async def avalidate_from_response(self, resp: Response) -> BaseOutputSchema | None:
        """Async helper to extract and validate structured output from a response.

        Uses `adecode` and returns:
          - A validated model on success.
          - None if extraction/validation fails.
        """
        with service_span_sync(
            "simcore.codec.validate",
            attributes={
                "simcore.codec": self.__class__.__name__,
                "simcore.schema": getattr(type(self).response_schema, "__name__", None),
            },
        ):
            try:
                return await self.adecode(resp)
            except CodecDecodeError:
                return None

    def validate_from_response(self, resp: Response) -> BaseOutputSchema | None:
        """Sync wrapper for `avalidate_from_response`.

        Do not override in subclasses; implement async behavior in `adecode` instead.
        """
        return async_to_sync(self.avalidate_from_response)(resp)

    # ---- Extraction --------------------------------------------------------
    def extract_structured_candidate(self, resp: Response) -> dict | None:
        """Best-effort structured payload extraction.

        Priority: provider-native → OutputJsonContent → JSON text → tool-result JSON.
        """
        with service_span_sync("simcore.codec.extract", attributes={"simcore.codec": self.__class__.__name__}):
            for extractor in (
                self._extract_from_provider,
                self._extract_from_json_content,
                self._extract_from_json_text,
                self._extract_from_tool_result,
            ):
                try:
                    data = extractor(resp)
                except Exception:
                    data = None
                if isinstance(data, dict):
                    return data
            return None

    @staticmethod
    def _extract_from_provider(resp: Response) -> dict | None:
        obj = (resp.provider_meta or {}).get("structured")
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _extract_from_json_content(resp: Response) -> dict | None:
        """Extract structured payload from OutputJsonContent, if present."""
        for msg in getattr(resp, "output", []) or []:
            for part in getattr(msg, "content", []) or []:
                if isinstance(part, OutputJsonContent):
                    value = getattr(part, "value", None)
                    if isinstance(value, dict):
                        return value
        return None

    @staticmethod
    def _extract_from_json_text(resp: Response) -> dict | None:
        for msg in getattr(resp, "output", []) or []:
            for part in getattr(msg, "content", []) or []:
                if isinstance(part, OutputTextContent):
                    text = getattr(part, "text", None)
                    if not text:
                        continue
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        continue
        return None

    @staticmethod
    def _extract_from_tool_result(resp: Response) -> dict | None:
        for msg in getattr(resp, "output", []) or []:
            for part in getattr(msg, "content", []) or []:
                if isinstance(part, OutputToolResultContent):
                    # Prefer native JSON field if available
                    if getattr(part, "result_json", None) and isinstance(part.result_json, dict):
                        return part.result_json

                    mime = (getattr(part, "mime_type", "") or "").split(";", 1)[0].strip().lower()
                    if mime in {"application/json", "text/json"} and getattr(part, "data_b64", None):
                        try:
                            raw = base64.b64decode(part.data_b64).decode("utf-8")
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                    return None
        return None
