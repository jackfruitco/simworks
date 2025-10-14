# simcore_ai/providers/base.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Iterable, Optional, Protocol

from ..tracing import service_span_sync
from ..types import (
    LLMRequest,
    LLMRequestMessage,
    LLMResponse,
    LLMResponseItem,
    LLMStreamChunk,
    LLMTextPart,
    LLMToolResultPart,
    LLMToolCall,
)
from ..types.tools import BaseLLMTool
from simcore_ai.exceptions import ProviderError, ProviderSchemaUnsupported

logger = logging.getLogger(__name__)




class BaseProvider(ABC):
    # ---------------------------------------------------------------------
    # Rate-limit observability
    # ---------------------------------------------------------------------
    def record_rate_limit(
        self,
        *,
        status_code: int | None = None,
        retry_after_ms: int | None = None,
        detail: str | None = None,
    ) -> None:
        """Emit a short span when a rate limit is encountered.

        Providers may call this directly; the AIClient also tries to call it when
        it detects a 429-like error from the SDK/HTTP layer.
        """
        try:
            with service_span_sync(
                "ai.provider.ratelimit",
                attributes={
                    "ai.provider_name": getattr(self, "name", self.__class__.__name__),
                    "http.status_code": status_code if status_code is not None else 429,
                    "retry_after_ms": retry_after_ms,
                },
            ):
                if detail:
                    logger.debug("%s rate-limited: %s", self.name, detail)
        except Exception:  # pragma: no cover - never break on tracing errors
            pass
    """
    Abstract base class for all AI providers.

    Key ideas:
      - Providers implement `call` (non-stream) and `stream` (streaming) using their SDKs.
      - Providers supply *hook methods* to extract text, outputs, usage, and meta
        from the raw SDK response. The shared `adapt_response` turns those into an
        `LLMResponse` via the normalized LLMResponseItem → DTO flow.
    """

    name: str
    description: str

    def __init__(self, *, name: str, description: str | None = None, **_: object) -> None:
        """Common initializer for providers.
        Only standardizes identity fields; provider-specific params are handled by subclasses.
        """
        self.name = name
        self.description = description or name

    _tool_adapter: Optional["BaseProvider.ToolAdapter"] = None

    # ---------------------------------------------------------------------
    # Public provider API
    # ---------------------------------------------------------------------
    @abstractmethod
    async def call(self, req: LLMRequest, timeout: float | None = None) -> LLMResponse:
        ...

    @abstractmethod
    async def stream(self, req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        ...

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIProvider {self.name}>"

    def _provider_namespace_key(self) -> str:
        """
        Return a stable provider namespace like 'simcore.ai_v1.providers.<label>'
        regardless of whether the class lives in ...<label>, ...<label>.base, etc.
        """
        mod = self.__class__.__module__
        parts = mod.split(".")
        try:
            i = parts.index("providers")
            label = parts[i + 1]
            return ".".join(parts[: i + 2])
        except (ValueError, IndexError):
            return mod

    # ---------------------------------------------------------------------
    # Normalization/adaptation (provider-agnostic core + provider hooks)
    # ---------------------------------------------------------------------
    def adapt_response(
            self, resp: Any, *, schema_cls: type | None = None
    ) -> LLMResponse:
        """
        Provider-agnostic response construction pipeline.

        Steps:
          1) Extract primary assistant text (if any) and add as an LLMResponseItem with LLMTextPart.
          2) Parse structured text to the declared Pydantic schema (optional, best-effort) via _maybe_parse_to_schema.
             (This is for app-side validation/debug; the normalized messages are still built from parts.)
          3) Inspect provider-specific outputs (images/tools) and convert into normalized tool calls and
             LLMToolResultPart messages.
          4) Attach usage and provider_meta.

        Args:
            resp: Provider-specific response object
            schema_cls: Optional Pydantic model class to parse structured text into
        """
        with service_span_sync(
            "ai.response.normalize",
            attributes={
                "ai.provider_name": getattr(self, "name", self.__class__.__name__),
            },
        ) as span:
            messages: list[LLMResponseItem] = []
            tool_calls: list[LLMToolCall] = []

            # 1) Primary assistant text
            text_out = self._extract_text(resp)
            if text_out:
                messages.append(LLMResponseItem(role="assistant", content=[LLMTextPart(text=text_out)]))

            # 2) Optional schema parse (best-effort); does not alter normalized message parts
            parsed = None
            if schema_cls is not None and text_out:
                parsed = self._maybe_parse_to_schema(text_out, schema_cls)

            # 3) Provider outputs -> tool results / attachments
            from uuid import uuid4
            for obj in self._extract_outputs(resp) or []:
                try:
                    # 3a) Let the provider fully normalize arbitrary tool outputs (preferred path)
                    pair = self._normalize_tool_output(obj)
                    if pair is not None:
                        call, part = pair
                        tool_calls.append(call)
                        messages.append(LLMResponseItem(role="assistant", content=[part]))
                        continue

                    # 3b) Generic fallback: image-like results
                    if self._is_image_output(obj):
                        call_id = getattr(obj, "id", None) or str(uuid4())
                        tool_calls.append(LLMToolCall(call_id=call_id, name="image_generation", arguments={}))
                        b64 = getattr(obj, "result", None) or getattr(obj, "b64", None)
                        mime = getattr(obj, "mime_type", None) or "image/png"
                        if b64:
                            messages.append(
                                LLMResponseItem(
                                    role="assistant",
                                    content=[LLMToolResultPart(call_id=call_id, mime_type=mime, data_b64=b64)],
                                )
                            )
                        continue

                    # 3c) Unrecognized output item: ignore silently but keep diagnostics enabled
                    logger.debug("provider '%s':: unhandled output item type: %s", getattr(self, "name", self), type(obj).__name__)
                except Exception:
                    logger.debug("provider '%s':: failed to adapt an output item; skipping", getattr(self, "name", self), exc_info=True)
                    continue

            # Attach summary attributes for observability
            try:
                span.set_attribute("ai.parts.count", len(messages))
                span.set_attribute("ai.tool_calls.count", len(tool_calls))
                span.set_attribute("ai.text.present", bool(text_out))
            except Exception:
                pass

            return LLMResponse(
                messages=messages,
                usage=self._extract_usage(resp),
                tool_calls=tool_calls,
                provider_meta=self._extract_provider_meta(resp),
            )

    # ---------------------------------------------------------------------
    # Response Format / Schema (provider-specific adapters + _wrap_schema func)
    # ---------------------------------------------------------------------
    def build_final_schema(
            self, req: "LLMRequest"
    ) -> None:
        """Compile adapters for the request's response format and attach back to the request.

        Flow:
            - Read `req.response_format_cls`
            - Apply provider-specific adapters via the central compiler
            - Wrap the adapted response format into provider-specific payload (e.g., OpenAI Responses `response_format`)
            - Attach the final result to the `req.response_format` field.

        Args:
            req: LLMRequest with `response_format_cls` set

        Returns:
            None (modifies `req` in-place)
        """
        with service_span_sync(
            "ai.schema.build_final",
            attributes={
                "ai.provider_name": getattr(self, "name", self.__class__.__name__),
            },
        ):
            try:
                # Compile/adapt into provider-friendly JSON Schema
                with service_span_sync("ai.schema.adapters", attributes={"ai.provider_name": getattr(self, "name", self.__class__.__name__)}):
                    adapted = self._apply_schema_adapters(req)
                if adapted is None:
                    return  # no schema provided; nothing to do

                # (Optional) keep for diagnostics
                try:
                    setattr(req, "response_format_adapted", adapted)
                except Exception:
                    pass

                meta = getattr(req, "_schema_meta", {"name": "response", "strict": True})
                wrapped = self._wrap_schema(adapted, meta)
                # If provider returns None (no envelope), use adapted schema as-is
                if wrapped is not None and not isinstance(wrapped, dict):
                    raise ProviderError(f"{self.name}._wrap_schema must return dict|None, got {type(wrapped).__name__}")
                req.response_format = wrapped or adapted
            except Exception:
                logger.exception("provider '%s':: build_final_schema failed", getattr(self, "name", self))

    def _apply_schema_adapters(self, req: "LLMRequest") -> dict | None:
        """Apply provider-specific schema adapters to the request's response format.

        This is the central point for provider-specific schema adaptation/override.
        """
        # Prefer new field; allow legacy alias for transition
        source = getattr(req, "response_format_cls", None) or getattr(req, "schema_cls", None)
        if source is None:
            return None

        with service_span_sync(
            "ai.schema.compile",
            attributes={
                "ai.provider_name": getattr(self, "name", self.__class__.__name__),
                "ai.output_schema_cls": getattr(source, "__name__", type(source).__name__),
            },
        ):
            # Derive base JSON Schema
            try:
                base_schema = source.model_json_schema()  # Pydantic v2 model class
            except Exception:
                base_schema = source  # already a dict-like schema

            if not isinstance(base_schema, dict):
                raise ProviderSchemaUnsupported("output_schema_cls must be a Pydantic model class or a JSON Schema dict")

            # Run provider adapters
            from ..schemas.compiler import compile_schema
            compiled = compile_schema(base_schema, provider=self.name)
            if not isinstance(compiled, dict):
                raise ProviderSchemaUnsupported("compile_schema must return a dict JSON Schema")
            return compiled

    def _wrap_schema(self, compiled_schema: dict, meta: dict | None = None) -> dict | None:
        """
        Default no-op wrapper. Providers that support structured output envelopes should override this
        to return a provider-specific payload (e.g., OpenAI Responses `response_format`). If None is
        returned, the caller will use `compiled_schema` directly.
        """
        return None


    # ---------------------------------------------------------------------
    # Provider-specific Response HOOKS (override in concrete providers)
    # ---------------------------------------------------------------------
    def _extract_text(self, resp: Any) -> Optional[str]:
        """Return the provider's primary text output, if any."""
        ...

    def _extract_outputs(self, resp: Any) -> Iterable[Any]:
        """Yield provider output items (images, tool calls, etc.)."""
        ...

    def _is_image_output(self, item: Any) -> bool:
        """Return True if the output item represents an image generation result."""
        ...

    def _extract_usage(self, resp: Any) -> dict:
        """Return a normalized usage dict (input/output/total tokens, etc.)."""
        ...

    def _extract_provider_meta(self, resp: Any) -> dict:
        """Return provider-specific metadata for diagnostics (model, ids, raw dump)."""
        ...

    def _normalize_tool_output(self, item: Any) -> Optional[tuple[LLMToolCall, LLMToolResultPart]]:
        """
        Convert a provider-native output item (tool call/result, images, audio, etc.) into a
        normalized (LLMToolCall, LLMToolResultPart) pair. Return None if the item is not a tool
        output you recognize, and the base class will try generic fallbacks.
        """
        return None
    # ---------------------------------------------------------------------
    # Tools
    # ---------------------------------------------------------------------
    class ToolAdapter(Protocol):
        def to_provider(self, tool: BaseLLMTool) -> Any: ...
        def from_provider(self, tool: Any) -> BaseLLMTool: ...

    # -- Tool adaptation helpers -------------------------------------------------
    def set_tool_adapter(self, adapter: "BaseProvider.ToolAdapter") -> None:
        """Register a ToolAdapter for this provider.
        Concrete providers can call this in __init__, or the caller can inject one.
        """
        self._tool_adapter = adapter

    def _tools_to_provider(self, tools: Optional[list[BaseLLMTool]]) -> Optional[list[Any]]:
        """Convert our DTO BaseLLMTool list into provider-native tool specs.
        Returns None if no adapter is registered or tools is falsy.
        """
        if not tools or not getattr(self, "_tool_adapter", None):
            return None
        return [self._tool_adapter.to_provider(t) for t in tools]  # type: ignore[attr-defined]

    def _tools_from_provider(self, provider_tools: Optional[Iterable[Any]]) -> list[BaseLLMTool]:
        """Convert provider-native tool specs into our BaseLLMTool DTOs.
        Returns an empty list if no adapter is registered or input is falsy.
        """
        if not provider_tools or not getattr(self, "_tool_adapter", None):
            return []
        return [self._tool_adapter.from_provider(t) for t in provider_tools]  # type: ignore[attr-defined]

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------
    @staticmethod
    def _maybe_parse_to_schema(text: str, schema_cls: type) -> Any:
        """Best-effort parse of `text` into `schema_cls` via Pydantic v2 API."""
        try:
            # Prefer JSON if schema expects JSON; fall back to plain model_validate
            return schema_cls.model_validate_json(text)
        except Exception:
            try:
                return schema_cls.model_validate(text)
            except Exception:
                return None
