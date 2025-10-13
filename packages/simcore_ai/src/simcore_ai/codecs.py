# simcore_ai/codecs/base.py
from __future__ import annotations

from abc import ABC
from typing import Any
import base64
import json

from pydantic import BaseModel, ValidationError

from .types import LLMResponse, LLMTextPart, LLMToolResultPart
from .types import StrictOutputSchema


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
    """

    #: Unique registry key for this codec (e.g., "feedback_v1_chatlab")
    name: str

    #: Pydantic model class describing the expected structured output
    schema_cls: type[StrictOutputSchema]

    #: Optional metadata to guide provider wrapping (e.g., name/strict flags)
    schema_meta: dict[str, Any] | None = None

    # ----------------------------------------------------------------------
    # Schema utilities
    # ----------------------------------------------------------------------
    def json_schema(self) -> dict:
        """Return the JSON Schema for this codec's Pydantic model class."""
        return self.schema_cls.model_json_schema()

    # ----------------------------------------------------------------------
    # Validation helpers
    # ----------------------------------------------------------------------
    def validate_dict(self, data: dict) -> BaseModel:
        """Validate a raw dict to the Pydantic model defined by `schema_cls`."""
        return self.schema_cls.model_validate(data)

    def validate_from_response(self, resp: LLMResponse) -> BaseModel | None:
        """
        Best-effort extractor + validator.

        Returns a Pydantic model instance if structured output can be extracted
        and validated, otherwise returns None.
        """
        candidate = self.extract_structured_candidate(resp)
        if candidate is None:
            return None
        try:
            return self.validate_dict(candidate)
        except ValidationError:
            return None

    # ----------------------------------------------------------------------
    # Extraction helper
    # ----------------------------------------------------------------------
    def extract_structured_candidate(self, resp: LLMResponse) -> dict | None:
        """
        Try to find a structured JSON object in a normalized LLMResponse.

        Priority:
          1) Provider-supplied object in resp.provider_meta['structured']
          2) First assistant text part that parses as JSON
          3) First tool result part with JSON mime, base64-decoded and parsed
        """
        # 1) Provider-provided
        obj = resp.provider_meta.get("structured")
        if isinstance(obj, dict):
            return obj

        # 2) Text → JSON
        for item in getattr(resp, "outputs", []) or []:
            for part in getattr(item, "content", []) or []:
                if isinstance(part, LLMTextPart):
                    try:
                        return json.loads(part.text)
                    except Exception:
                        pass

        # 3) Tool result → JSON
        for item in getattr(resp, "outputs", []) or []:
            for part in getattr(item, "content", []) or []:
                if isinstance(part, LLMToolResultPart) and (
                    part.mime_type or ""
                ).startswith(("application/json", "text/json")):
                    try:
                        raw = base64.b64decode(part.data_b64).decode("utf-8")
                        return json.loads(raw)
                    except Exception:
                        pass

        return None