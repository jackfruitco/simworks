# simcore_ai/components/providerkit/base.py


import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, AsyncIterator, Optional, Protocol

from simcore_ai.tracing import service_span_sync
from simcore_ai.types import (
    Request,
    Response,
    StreamChunk,
    LLMToolCall, )
from simcore_ai.types.messages import OutputItem, UsageContent
from simcore_ai.types.content import ContentRole
from simcore_ai.types.output import OutputTextContent, OutputToolResultContent
from simcore_ai.types.tools import BaseLLMTool

logger = logging.getLogger(__name__)

__all__ = ["BaseProvider"]


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
        """Emit a short spaxn when a rate limit is encountered.

        Providers may call this directly; the AIClient also tries to call it when
        it detects a 429-like error from the SDK/HTTP layer.
        """
        try:
            attrs = {
                "simcore.provider_name": getattr(self, "name", self.__class__.__name__),
                "http.status_code": status_code if status_code is not None else 429,
            }
            pk = getattr(self, "provider_key", None)
            pl = getattr(self, "provider_label", None)
            if pk is not None:
                attrs["simcore.provider_key"] = pk
            if pl is not None:
                attrs["simcore.provider_label"] = pl
            if retry_after_ms is not None:
                attrs["retry_after_ms"] = retry_after_ms

            with service_span_sync("simcore.provider.ratelimit", attributes=attrs):
                if detail:
                    logger.debug("%s rate-limited: %s", self.name, detail)
        except Exception:  # pragma: no cover - never break on tracing errors
            pass

    """
    Abstract base class for all AI providers.

    Key ideas:
      - Providers implement `call` (non-stream) and `stream` (streaming) using their SDKs.
      - Providers supply *hook methods* to extract text, output, usage, and meta
        from the raw SDK response. The shared `adapt_response` turns those into a
        `Response` via the normalized OutputItem → DTO flow (text/output/usage/meta normalization).
    """

    name: str
    description: str

    def __init__(
            self,
            *,
            name: str,
            description: str | None = None,
            provider_key: Optional[str] = None,
            provider_label: Optional[str] = None,
            **_: object
    ) -> None:
        """Common initializer for providers.
        Only standardizes identity fields; provider-specific params are handled by subclasses.
        """
        self.name = name
        self.description = description or name
        # Optional observability fields (set by the factory when available)
        self.provider_key = provider_key
        self.provider_label = provider_label

    _tool_adapter: Optional["BaseProvider.ToolAdapter"] = None

    # ---------------------------------------------------------------------
    # Public provider API (async-first contracts)
    # ---------------------------------------------------------------------
    # Providers should implement **async** methods for both non-stream and stream modes.
    # If you have a sync-only SDK, you may still integrate by running the sync call in a thread
    # (the AIClient will do this via `asyncio.to_thread` when it detects a sync `call`).
    #
    # Streaming MUST be async: `async def stream(self, req) -> AsyncIterator[StreamChunk]`.
    # Sync streaming is not supported by the client adapter.

    @abstractmethod
    async def call(self, req: Request, timeout: float | None = None) -> Response:
        """Canonical async, non-streaming request.

        Implementations MUST be async when subclassing BaseProvider. If your concrete
        provider relies on a sync-only SDK, consider not subclassing or ensure your
        implementation awaits on an internal `asyncio.to_thread(...)` call to offload
        the blocking work. The `AIClient` also provides a safety net when interacting
        with provider-like objects that expose a sync `call(...)` by running them in a
        worker thread to avoid blocking the event loop.
        """
        ...

    @abstractmethod
    async def stream(self, req: Request) -> AsyncIterator[StreamChunk]:
        """Canonical async streaming interface.

        MUST be implemented as an async generator yielding `StreamChunk` items.
        The core client requires an async `stream(...)` and will raise if missing.
        """
        ...

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIProvider {self.name}>"

    async def healthcheck(self, *, timeout: float | None = None) -> tuple[bool, str]:
        """
        Default provider healthcheck.

        Returns:
            (ok, detail): ok=True if healthy, detail is a short message.
        """
        # Default behavior (safe no-op): just report the provider is constructed.
        # Concrete providers SHOULD override with a minimal live call.
        try:
            return True, f"{getattr(self, 'name', self.__class__.__name__)} ready"
        except Exception as exc:
            return False, f"init error: {exc!s}"

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
            self, resp: Any, *, output_schema_cls: type | None = None
    ) -> Response:
        """
        Provider-agnostic response construction pipeline.

        Steps:
          1) Extract primary assistant text (if any) and add as an OutputItem with OutputTextContent.
          2) Inspect provider-specific output (images/tools) and convert into normalized tool calls and
             OutputToolResultContent input.
          3) Attach usage and provider_meta.

        Args:
            resp: Provider-specific response object
            output_schema_cls: (unused, for call-site compatibility)
        """
        # output_schema_cls is retained for call-site compatibility but is no longer used.
        _ = output_schema_cls
        with service_span_sync(
                "simcore.response.adapt",
                attributes={
                    "simcore.provider_name": getattr(self, "name", self.__class__.__name__),
                    "simcore.provider_key": getattr(self, "provider_key", None),
                    "simcore.provider_label": getattr(self, "provider_label", None),
                },
        ) as span:
            messages: list[OutputItem] = []
            tool_calls: list[LLMToolCall] = []

            # 1) Primary assistant text
            text_out = self._extract_text(resp)
            if text_out:
                messages.append(
                    OutputItem(
                        role=ContentRole.ASSISTANT,
                        content=[OutputTextContent(text=text_out)],
                    )
                )

            # 2) Provider output -> tool results / attachments
            from uuid import uuid4
            for obj in self._extract_outputs(resp) or []:
                try:
                    # 3a) Let the provider fully normalize arbitrary tool output (preferred path)
                    pair = self._normalize_tool_output(obj)
                    if pair is not None:
                        call, part = pair
                        tool_calls.append(call)
                        messages.append(
                            OutputItem(
                                role=ContentRole.ASSISTANT,
                                content=[part],
                            )
                        )
                        continue

                    # 3b) Generic fallback: image-like results
                    if self._is_image_output(obj):
                        call_id = getattr(obj, "id", None) or str(uuid4())
                        tool_calls.append(LLMToolCall(call_id=call_id, name="image_generation", arguments={}))
                        b64 = getattr(obj, "result", None) or getattr(obj, "b64", None)
                        mime = getattr(obj, "mime_type", None) or "image/png"
                        if b64:
                            messages.append(
                                OutputItem(
                                    role=ContentRole.ASSISTANT,
                                    content=[
                                        OutputToolResultContent(
                                            call_id=call_id,
                                            mime_type=mime,
                                            data_b64=b64,
                                        )
                                    ],
                                )
                            )
                        continue

                    # 3c) Unrecognized output item: ignore silently but keep diagnostics enabled
                    logger.debug("provider '%s':: unhandled output item type: %s", getattr(self, "name", self),
                                 type(obj).__name__)
                except Exception:
                    logger.debug("provider '%s':: failed to adapt an output item; skipping",
                                 getattr(self, "name", self), exc_info=True)
                    continue

            # Attach summary attributes for observability
            try:
                span.set_attribute("simcore.parts.count", len(messages))
                span.set_attribute("simcore.tool_calls.count", len(tool_calls))
                span.set_attribute("simcore.text.present", bool(text_out))
            except Exception:
                pass

            usage_data = self._extract_usage(resp)
            usage = None
            if usage_data:
                try:
                    usage = UsageContent.model_validate(usage_data)
                except Exception:
                    usage = UsageContent(**usage_data) if isinstance(usage_data, dict) else None

            return Response(
                output=messages,
                usage=usage,
                tool_calls=tool_calls,
                provider_meta=self._extract_provider_meta(resp),
            )

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

    def _normalize_tool_output(self, item: Any) -> Optional[tuple[LLMToolCall, OutputToolResultContent]]:
        """
        Convert a provider-native output item (tool call/result, images, audio, etc.) into a
        normalized (LLMToolCall, OutputToolResultContent) pair. Return None if the item is not a tool
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

    def supports_streaming(self) -> bool:
        """Return True if this provider exposes an async `stream` method."""
        try:
            return inspect.iscoroutinefunction(getattr(self, "stream", None))
        except Exception:
            return False
