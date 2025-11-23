# simcore_ai/components/codecs/base.py


import base64
import json
import logging
from abc import ABC
from typing import Any, ClassVar

from asgiref.sync import async_to_sync
from pydantic import ValidationError

from .exceptions import CodecDecodeError, CodecSchemaError
from ..schemas.base import BaseOutputSchema
from ...components import BaseComponent
from ...identity import IdentityMixin
from ...tracing import service_span_sync
from ...types import Request, Response, LLMStreamChunk, LLMTextPart, LLMToolResultPart

logger = logging.getLogger(__name__)


class BaseCodec(IdentityMixin, BaseComponent, ABC):
    """Provider-agnostic, per-call codec for structured outputs.

  Responsibilities
  ----------------
  • Advertise a Pydantic schema via `output_schema_cls`.
  • During encode, set provider-agnostic hints on the request (e.g., `output_schema_cls`, `output_schema_meta`).
  • During decode, validate normalized responses/stream chunks to that schema.
  • Never call provider adapters or SDKs; providers wrap schemas via their own adapters.
  """

    output_schema_cls: ClassVar[type[BaseOutputSchema] | None] = None

    def __init__(self) -> None:
        super().__init__()
        self.output_schema_meta: dict[str, Any] | None = None
        self._stream_buffer: list[Any] | None = None

    @classmethod
    async def aget_registry(cls):
        from simcore_ai.registry.singletons import codecs as _codecs
        return _codecs

    # ---- Init ----------------------------------------------------------
    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if not getattr(cls, "abstract", False):
            registry = async_to_sync(cls.aget_registry)()
            registry.register(cls)

    # ---- Lifecycle: setup/teardown are optional ----------------------------
    async def asetup(self, *, context: dict[str, Any] | None = None) -> None:
        self._stream_buffer = []

    async def ateardown(self, *, context: dict[str, Any] | None = None) -> None:
        self._stream_buffer = None

    # ---- Encode -----------------------------------------------------------
    async def aencode(self, req: Request) -> None:
        """
        Attach provider-agnostic structured-output hints to the request.

        Sets:
          - req.output_schema_cls = self.output_schema_cls
          - req.output_schema_meta (optional) if not already set, from self.output_schema_meta
        """
        with service_span_sync(
                "simcore.codec.encode",
                attributes={
                    "simcore.codec": self.__class__.__name__,
                    "simcore.output_schema": getattr(type(self).output_schema_cls, "__name__", "<Not Set>"),
                },
        ):
            # No schema? Nothing to encode.
            if type(self).output_schema_cls is None:
                return

            try:
                # Attach cls and meta if not already attached by service
                if getattr(req, "output_schema_cls", None) is None:
                    req.output_schema_cls = type(self).output_schema_cls
                if getattr(req, "output_schema_meta", None) is None and self.output_schema_meta:
                    req.output_schema_meta = dict(self.output_schema_meta)
            except Exception as e:
                raise CodecSchemaError("Failed to encode request hints for structured output") from e

    def encode(self, req: Request) -> None:
        return async_to_sync(self.aencode)(req)

    # ---- Decode -----------------------------------------------------------
    async def adecode(self, resp: Response) -> BaseOutputSchema | None:
        """
        Extract and validate structured output from a non-stream response.
        Return a validated model, or None if no structured payload exists.
        """
        if type(self).output_schema_cls is None:
            return None
        with service_span_sync(
                "simcore.codec.decode",
                attributes={
                    "simcore.codec": self.__class__.__name__,
                    "simcore.output_schema": getattr(type(self).output_schema_cls, "__name__", "<Not Set>"),
                },
        ):
            candidate = self.extract_structured_candidate(resp)
            if candidate is None:
                return None
            return self.validate_dict(candidate)

    async def arun(self, resp: Response) -> BaseOutputSchema | None:  # deprecated path
        return await self.adecode(resp)

    # ---- Streaming hooks --------------------------------------------------
    async def adecode_chunk(self, chunk: LLMStreamChunk, *, is_final: bool = False) -> tuple[
        BaseOutputSchema | None, bool]:
        """
        Consume a streaming chunk. Return (partial_model_or_None, done_bool).
        Default implementation accumulates nothing and never finishes early.
        """
        return None, False

    async def afinalize_stream(self) -> BaseOutputSchema | None:
        """
        Finalize accumulated streaming state into a validated model (or None).
        Default: no accumulation; return None.
        """
        return None

    # ---- Schema utilities --------------------------------------------------
    def json_schema(self) -> dict:
        if type(self).output_schema_cls is None:
            raise CodecSchemaError(f"Codec '{self.__class__.__name__}' has no 'output_schema_cls' defined")
        try:
            return type(self).output_schema_cls.model_json_schema()
        except Exception as e:
            raise CodecSchemaError(
                f"Failed to build JSON schema for codec '{self.__class__.__name__}'"
            ) from e

    # ---- Validation --------------------------------------------------------
    def validate_dict(self, data: dict[str, Any]) -> BaseOutputSchema:
        if type(self).output_schema_cls is None:
            raise CodecSchemaError(f"Codec '{self.__class__.__name__}' has no 'output_schema_cls' defined")
        try:
            return type(self).output_schema_cls.model_validate(data)
        except ValidationError as e:
            raise CodecDecodeError(
                f"Validation failed for codec '{self.__class__.__name__}'"
            ) from e

    async def avalidate_from_response(self, resp: Response) -> BaseOutputSchema | None:
        """
        Async helper to extract and validate structured output from a response.

        Uses `adecode` and returns:
          - A validated model on success.
          - None if extraction/validation fails.
        """
        with service_span_sync(
                "simcore.codec.validate",
                attributes={
                    "simcore.codec": self.__class__.__name__,
                    "simcore.schema": getattr(type(self).output_schema_cls, "__name__", None),
                },
        ):
            try:
                return await self.adecode(resp)
            except CodecDecodeError:
                return None

    def validate_from_response(self, resp: Response) -> BaseOutputSchema | None:
        """
        Sync wrapper for `avalidate_from_response`.

        Do not override in subclasses; implement async behavior in `arun` instead.
        """
        return async_to_sync(self.avalidate_from_response)(resp)

    # ---- Extraction --------------------------------------------------------
    def extract_structured_candidate(self, resp: Response) -> dict | None:
        """Priority: provider-native → JSON text → tool-result JSON."""
        with service_span_sync("simcore.codec.extract", attributes={"simcore.codec": self.__class__.__name__}):
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
    def _extract_from_provider(resp: Response) -> dict | None:
        obj = (resp.provider_meta or {}).get("structured")
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _extract_from_json_text(resp: Response) -> dict | None:
        for msg in getattr(resp, "outputs", []) or []:
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
    def _extract_from_tool_result(resp: Response) -> dict | None:
        for msg in getattr(resp, "outputs", []) or []:
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
