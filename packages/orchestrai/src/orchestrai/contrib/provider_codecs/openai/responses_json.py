# orchestrai/contrib/provider_codecs/openai/responses_json.py
"""
OpenAI Responses JSON codec.

This codec is responsible for:
  - Taking a backend-agnostic response schema (Pydantic model class or JSON Schema dict)
    from the Request and adapting it for the OpenAI Responses API.
  - Producing the backend-specific JSON payload that will be sent via the `text` parameter.
  - Optionally validating structured output from a Response back into the declared schema.

It is intentionally OpenAI-specific but still registered in the global codecs registry,
keyed by identity (namespace='openai', kind='responses', name='json').
"""

import logging
from typing import Any, ClassVar, Sequence

from pydantic import ValidationError

logger = logging.getLogger(__name__)

from ...provider_backends.openai.constants import PROVIDER_NAME
from ...provider_backends.openai.schema.adapt import OpenaiFormatAdapter
from ....components.codecs import BaseCodec
from ....components.codecs.exceptions import CodecDecodeError, CodecSchemaError
from ....components.schemas import BaseSchemaAdapter
from ....decorators import codec
from ....tracing import service_span_sync
from ....types import Request, Response


class OpenAiNamespaceMixin:
    """Mixin for OpenAI codecs. Sets the codec namespace and backend name."""
    namespace: ClassVar[str] = PROVIDER_NAME
    provider_name: ClassVar[str] = PROVIDER_NAME


class OpenAIResponsesBaseCodec(OpenAiNamespaceMixin, BaseCodec):
    """Base class for OpenAI Responses codecs."""
    kind: ClassVar[str] = "responses"


@codec(name="json")
class OpenAIResponsesJsonCodec(OpenAIResponsesBaseCodec):
    """Codec for OpenAI Responses JSON structured output.

    Encode:
      - Checks schema was validated for OpenAI (during decoration)
      - Uses cached validated schema
      - Applies format adapter (wraps in OpenAI envelope)
      - Attaches to request.provider_response_format

    Decode:
      - Extracts structured output from response
      - Validates into original Pydantic schema
      - Returns typed model instance
    """

    abstract: ClassVar[bool] = False

    # This codec is schema-agnostic at the class level; it relies on the Request
    # to provide the concrete Pydantic schema (Request.response_schema).
    output_schema_cls: ClassVar[type | None] = None

    # Format adapter (wraps schema in OpenAI envelope)
    # FlattenUnions removed - nested unions are now supported by OpenAI
    schema_adapters: ClassVar[Sequence[BaseSchemaAdapter]] = (
        OpenaiFormatAdapter(order=999),
    )

    async def aencode(self, req: Request) -> None:
        """Attach OpenAI Responses format to request.

        Assumes schema was already validated during @schema decoration.
        Uses cached validated schema for performance.
        """
        with service_span_sync(
                "orchestrai.codec.encode",
                attributes={
                    "orchestrai.codec": self.__class__.__name__,
                    "orchestrai.provider_name": "openai",
                    "orchestrai.codec.kind": "responses.json",
                },
        ):
            schema_cls = getattr(req, "response_schema", None)
            if schema_cls is None:
                return  # No structured output requested

            # Check schema was validated for OpenAI
            compatibility = getattr(schema_cls, "_provider_compatibility", {})
            if not compatibility.get("openai"):
                raise CodecSchemaError(
                    f"Schema {schema_cls.__name__} not validated for OpenAI. "
                    f"Ensure @schema decorator is applied and validation passed."
                )

            # Use cached validated schema (avoid regenerating)
            schema = getattr(
                schema_cls,
                "_validated_schema",
                None
            )

            # Fallback to generating schema if not cached (for backward compatibility)
            if schema is None:
                try:
                    schema = schema_cls.model_json_schema()
                    logger.warning(
                        f"Schema {schema_cls.__name__} not cached, generating at request time. "
                        f"This should not happen with @schema decorator."
                    )
                except Exception as exc:
                    raise CodecSchemaError(
                        f"{self.__class__.__name__}: failed to build JSON schema "
                        f"from response_schema={schema_cls!r}"
                    ) from exc

            # Apply format adapter (wraps in OpenAI envelope)
            adapted_schema = self._apply_adapters(schema)

            # Attach to request
            req.response_schema_json = schema  # Original for diagnostics
            setattr(req, "provider_response_format", adapted_schema)

    def _apply_adapters(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Apply schema adapters in order.

        Args:
            schema: Validated JSON Schema dict

        Returns:
            Adapted schema (wrapped in provider format)
        """
        result = schema
        for adapter in sorted(self.schema_adapters, key=lambda a: a.order):
            result = adapter.adapt(result)
        return result

    async def adecode(self, resp: Response) -> Any | None:
        """Decode structured output from a Response into the declared schema, if available.

        - Extracts the best candidate dict via BaseCodec.extract_structured_candidate.
        - If `Response.request.response_schema` is present and looks like a Pydantic model
          class, validates the dict into that model.
        - If no schema is available, returns the raw dict.
        """
        with service_span_sync(
                "orchestrai.codec.decode",
                attributes={
                    "orchestrai.codec": self.__class__.__name__,
                    "orchestrai.provider_name": "openai",
                    "orchestrai.codec.kind": "responses.json",
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

            # Fallback to service's schema if request schema not available
            if schema_cls is None:
                schema_cls = self._get_schema_from_service()

            # Fallback to codec's class-level schema
            if schema_cls is None:
                schema_cls = self.response_schema

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
