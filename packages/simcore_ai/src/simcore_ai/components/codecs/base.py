# simcore_ai/components/codecs/base.py
from __future__ import annotations

import base64
import json
from abc import ABC
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from asgiref.sync import async_to_sync

from simcore_ai.components import BaseComponent
from simcore_ai.identity import IdentityMixin
from simcore_ai.tracing import service_span_sync
from simcore_ai.types import LLMResponse, LLMTextPart, LLMToolResultPart
from simcore_ai.types.protocols import RegistryProtocol
from .exceptions import CodecDecodeError, CodecSchemaError
from ..schemas.base import BaseOutputSchema


@dataclass
class BaseCodec(IdentityMixin, BaseComponent, ABC):
    """Generic, stateless codec for validating and interpreting structured outputs."""
    abstract: ClassVar[bool] = True

    # Pydantic model (v2) describing expected structured output
    schema_cls: type[BaseOutputSchema]
    # Optional metadata passed to providers/wrappers
    schema_meta: dict[str, Any] | None = None

    # ---- Registry ----------------------------------------------------------
    @classmethod
    async def aget_registry(cls) -> RegistryProtocol["BaseCodec"]:
        from simcore_ai.registry.singletons import codecs
        return codecs  # type: ignore[return-value]


    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if not getattr(cls, "abstract", False):
            cls.get_registry().register(cls)

    # ---- Lifecycle: setup/teardown are optional ----------------------------
    async def asetup(self, *, context: dict[str, Any] | None = None) -> None:
        """Async setup hook. Ensures base lifecycle logic runs, then validates schema_cls."""
        await super().asetup(context=context)
        _ = self.schema_cls  # touch to fail fast if unset

    async def ateardown(self, *, context: dict[str, Any] | None = None) -> None:
        """Async teardown hook. Override in subclasses if needed."""
        await super().ateardown(context=context)

    # ---- Lifecycle: run does the actual work -------------------------------
    async def arun(self, resp: LLMResponse) -> BaseModel | None:
        """
        One-shot extraction + validation.

        Called by async runners (e.g. via `aexecute(resp)`).
        Returns a validated model or None if no valid structured payload is found.
        """
        with service_span_sync(
            "ai.codec.run",
            attributes={
                "ai.codec": self.__class__.__name__,
                "ai.schema": getattr(getattr(self, "schema_cls", None), "__name__", None),
            },
        ):
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None
            return self.validate_dict(candidate)

    # ---- Schema utilities --------------------------------------------------
    def json_schema(self) -> dict:
        try:
            return self.schema_cls.model_json_schema()
        except Exception as e:
            raise CodecSchemaError(
                f"Failed to build JSON schema for codec '{self.__class__.__name__}'"
            ) from e

    # ---- Validation --------------------------------------------------------
    def validate_dict(self, data: dict[str, Any]) -> BaseModel:
        try:
            return self.schema_cls.model_validate(data)
        except AttributeError as e:
            raise CodecSchemaError(
                f"Codec '{self.__class__.__name__}' has no 'schema_cls' defined"
            ) from e
        except ValidationError as e:
            raise CodecDecodeError(
                f"Validation failed for codec '{self.__class__.__name__}'"
            ) from e

    async def avalidate_from_response(self, resp: LLMResponse) -> BaseModel | None:
        """
        Async helper to extract and validate structured output from a response.

        Uses `arun` and returns:
          - A validated model on success.
          - None if extraction/validation fails.
        """
        with service_span_sync(
            "ai.codec.validate",
            attributes={
                "ai.codec": self.__class__.__name__,
                "ai.schema": getattr(getattr(self, "schema_cls", None), "__name__", None),
            },
        ):
            try:
                return await self.arun(resp)
            except CodecDecodeError:
                return None

    def validate_from_response(self, resp: LLMResponse) -> BaseModel | None:
        """
        Sync wrapper for `avalidate_from_response`.

        Do not override in subclasses; implement async behavior in `arun` instead.
        """
        return async_to_sync(self.avalidate_from_response)(resp)

    # ---- Extraction --------------------------------------------------------
    def extract_structured_candidate(self, resp: LLMResponse) -> dict | None:
        """Priority: provider-native → JSON text → tool-result JSON."""
        with service_span_sync("ai.codec.extract", attributes={"ai.codec": self.__class__.__name__}):
            for extractor in (
                    self._extract_from_provider,
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
    def _extract_from_provider(resp: LLMResponse) -> dict | None:
        obj = (resp.provider_meta or {}).get("structured")
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _extract_from_json_text(resp: LLMResponse) -> dict | None:
        for msg in getattr(resp, "messages", []) or []:
            for part in getattr(msg, "content", []) or []:
                if isinstance(part, LLMTextPart):
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
    def _extract_from_tool_result(resp: LLMResponse) -> dict | None:
        for msg in getattr(resp, "messages", []) or []:
            for part in getattr(msg, "content", []) or []:
                if isinstance(part, LLMToolResultPart):
                    mime = (getattr(part, "mime_type", "") or "").split(";", 1)[0].strip().lower()
                    if mime in {"application/json", "text/json"} and getattr(part, "data_b64", None):
                        try:
                            raw = base64.b64decode(part.data_b64).decode("utf-8")
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            continue
        return None
