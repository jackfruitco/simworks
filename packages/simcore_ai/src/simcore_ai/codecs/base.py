"""Base codec class for structured LLM output validation and interpretation.

Identity usage:
  The codec identity is composed of three parts: origin, bucket, and name.
  These are used for cross-layer registration and lookup, replacing any prior use of 'namespace'.

Responsibilities:
  - Declare the structured output contract via `schema_cls` (a StrictOutputSchema subclass).
  - Optionally provide `schema_meta` (e.g., {'name': '...', 'strict': True}) consumed by providers when wrapping.
  - Offer helpers to extract a structured JSON candidate from a normalized LLMResponse and validate it.

NOT responsible for:
  - Persistence, emitting signals, or any ORM/Django logic (do that in simcore_ai_django or app code).
  - Provider schema adaptation (that's handled by the provider/compiler layer).
"""

from __future__ import annotations

import base64
import json
from abc import ABC
from typing import Any

from pydantic import BaseModel, ValidationError

from simcore_ai.tracing import service_span_sync
from simcore_ai.types import LLMResponse, LLMTextPart, LLMToolResultPart
from simcore_ai.types import StrictOutputSchema
# Identity model for framework-agnostic codec keys
from simcore_ai.types.identity import Identity
from .exceptions import CodecDecodeError, CodecSchemaError


class BaseLLMCodec(ABC):
    """Base class for codecs that validate and interpret structured LLM outputs.

    Responsibilities in the core package:
      • Declare the structured output contract via `schema_cls`
        (a StrictOutputSchema subclass).
      • Optionally provide `schema_meta`
        (e.g., {'name': '...', 'strict': True}) consumed by providers when wrapping.
      • Offer helpers to extract a structured JSON candidate from a normalized
        LLMResponse and validate it.

    NOT responsible for:
      • Persistence, emitting signals, or any ORM/Django logic
        (do that in simcore_ai_django or app code).
      • Provider schema adaptation
        (that's handled by the provider/compiler layer).

    Identity:
      The codec may define `origin`, `bucket`, and `name` to align with service/registry identity.
      These correspond to the `Identity` model used for cross-layer registration and lookup.
    """

    #: Unique registry key for this codec (e.g., "feedback_v1_chatlab")
    name: str

    #: Pydantic model class describing the expected structured output
    schema_cls: type[StrictOutputSchema]

    #: Optional metadata to guide provider wrapping (e.g., name/strict flags)
    schema_meta: dict[str, Any] | None = None

    # Optional identity parts to align with services/registries
    origin: str = "default"
    bucket: str = "default"

    # ----------------------------------------------------------------------
    # Schema utilities
    # ----------------------------------------------------------------------
    def json_schema(self) -> dict:
        """Return the JSON Schema for this codec's Pydantic model class."""
        try:
            return self.schema_cls.model_json_schema()
        except Exception as e:
            raise CodecSchemaError(f"Failed to build JSON schema for codec '{getattr(self, 'name', None)}'") from e

    # ----------------------------------------------------------------------
    # Validation helpers
    # ----------------------------------------------------------------------
    def validate_dict(self, data: dict) -> BaseModel:
        """Validate a raw dict to the Pydantic model defined by `schema_cls`."""
        try:
            return self.schema_cls.model_validate(data)
        except AttributeError as e:
            raise CodecSchemaError(f"Codec '{getattr(self, 'name', None)}' has no 'schema_cls' defined") from e
        except ValidationError as e:
            raise CodecDecodeError(f"Validation failed for codec '{getattr(self, 'name', None)}'") from e

    def validate_from_response(self, resp: LLMResponse) -> BaseModel | None:
        """
        Best-effort extractor + validator.

        Returns a Pydantic model instance if structured output can be extracted
        and validated, otherwise returns None.
        """
        with service_span_sync(
                "ai.codec.validate",
                attributes={
                    "ai.codec": self.__class__.__name__,
                    "ai.schema": getattr(getattr(self, "schema_cls", None), "__name__", None),
                },
        ):
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None
            try:
                return self.validate_dict(candidate)
            except CodecDecodeError:
                return None

    # ----------------------------------------------------------------------
    # Extraction helper
    # ----------------------------------------------------------------------
    def extract_structured_candidate(self, resp: LLMResponse) -> dict | None:
        """
        Try to find a structured JSON object in a normalized LLMResponse.

        Priority:
          1) Provider-supplied object in resp.provider_meta['structured']
          2) First assistant text part from resp.messages that parses as JSON
          3) First tool result part from resp.messages with JSON mime, base64-decoded and parsed
        """
        with service_span_sync(
                "ai.codec.extract",
                attributes={"ai.codec": self.__class__.__name__},
        ):
            # 1) Provider-provided
            obj = resp.provider_meta.get("structured")
            if isinstance(obj, dict):
                return obj

            # 2) Text → JSON
            for item in getattr(resp, "messages", []) or []:
                for part in getattr(item, "content", []) or []:
                    if isinstance(part, LLMTextPart):
                        try:
                            return json.loads(part.text)
                        except Exception:
                            pass

            # 3) Tool result → JSON
            for item in getattr(resp, "messages", []) or []:
                for part in getattr(item, "content", []) or []:
                    if isinstance(part, LLMToolResultPart):
                        mime_type_normalized = (part.mime_type or "").split(";", 1)[0].strip().lower()
                        if mime_type_normalized in {"application/json", "text/json"} and part.data_b64:
                            try:
                                raw = base64.b64decode(part.data_b64).decode("utf-8")
                                return json.loads(raw)
                            except Exception:
                                pass

            return None

    # ----------------------------------------------------------------------
    # Identity helpers (framework-agnostic)
    # ----------------------------------------------------------------------
    @property
    def identity(self) -> Identity:
        return Identity(origin=self.origin, bucket=self.bucket, name=self.name)

    @property
    def identity_key2(self) -> tuple[str, str]:
        """Two-part key used by the core registry: (origin, f"{bucket}:{name}")"""
        ident = self.identity
        return ident.as_tuple2

    @property
    def identity_str(self) -> str:
        """Human-friendly identity string 'origin.bucket.name'."""
        return self.identity.to_string()
