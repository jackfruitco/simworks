# simcore_ai/providers/openai/base.py
"""
OpenAIProvider
==============

Concrete provider implementation for the OpenAI *Responses* API.

Responsibilities
----------------
- Translate normalized `Request` objects into OpenAI SDK calls.
- Normalize provider-native responses into our `Response` model using the
  provider-agnostic adaptation pipeline in `BaseProvider`.
- Provide provider-specific response-format wrapping (JSON Schema) and tool
  output normalization (e.g., image generation results).
- Emit rich tracing spans for observability.

Construction
------------
Instances are constructed by `simcore_ai.providers.factory.create_provider`, which
passes a resolved configuration:
    - api_key:      Final API key (already resolved with env/overrides).
    - base_url:     Optional custom endpoint.
    - default_model:Default model used if the request does not specify one.
    - timeout_s:    Request timeout in seconds.
    - name:         Semantic provider identity (e.g., "openai:prod").

This class does not fetch environment variables directly; resolution occurs in
the Django setup + provider factory layer.
"""

import logging
from typing import Any, Final, Literal
from uuid import uuid4

from openai import NOT_GIVEN, AsyncOpenAI
from openai.types.responses import Response as OpenAIResponse, EasyInputMessageParam
from openai.types.responses.response_output_item import ImageGenerationCall

from simcore_ai.tracing import service_span, service_span_sync, flatten_context as _flatten_context
from simcore_ai.types import (
    ToolResultContent,
    LLMToolCall,
    Request,
    Response,
)
from ..base import BaseProvider
from ..exceptions import ProviderError
from ..openai.tools import OpenAIToolAdapter

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final[Literal["openai"]] = "openai"


class OpenAIProvider(BaseProvider):
    """OpenAI Responses API provider."""

    def __init__(
            self,
            *,
            api_key: str | None,
            base_url: str | None = None,
            default_model: str | None = None,
            timeout_s: int = 60,
            name: str = PROVIDER_NAME,
            **kwargs: object,
    ) -> None:
        """
        Initialize the OpenAI provider.

        Args:
            api_key: Final API key to use for authentication (may be None in dev).
            base_url: Optional custom endpoint URL.
            default_model: Default model used when a request omits `req.model`.
            timeout_s: Default request timeout (seconds).
            name: Semantic provider name for logs/tracing (e.g., "openai:prod").
            **kwargs: Ignored; included for forward-compatibility.
        """
        self.api_key = api_key
        self.base_url = base_url or None
        self.default_model = default_model
        self.timeout_s = timeout_s

        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s)

        super().__init__(name=name, description="OpenAI Responses API")

        # Register tools adapter
        self.set_tool_adapter(OpenAIToolAdapter())

    async def healthcheck(self, *, timeout: float | None = None) -> tuple[bool, str]:
        """
        Minimal live check using Responses API; no tokens-heavy call.
        """
        try:
            # call OpenAI Responses API with ping message
            await self._client.responses.create(
                model=self.default_model or "gpt-4o-mini",
                input=[EasyInputMessageParam(role="user", content="ping")],
                max_output_tokens=16,
                timeout=timeout or min(self.timeout_s or 10, 10),
            )
            return True, "responses.create OK"
        except Exception as exc:
            # Optionally map rate limit / auth separately for clearer logs
            self.record_rate_limit(status_code=getattr(exc, "status_code", None), detail=str(exc))
            return False, f"openai error: {exc!s}"

    def _wrap_schema(self, adapted_schema: dict, meta: dict | None = None) -> dict | None:
        """
        Wrap a compiled JSON Schema into the OpenAI Responses `response_schema_json` envelope.

        Args:
            adapted_schema: Provider-adapted JSON Schema dictionary.
            meta: Optional metadata (`name`, `strict`) derived from the request.

        Returns:
            A dict payload suitable for `response_schema_json`, or None to use the schema directly.
        """
        if not adapted_schema:
            return None
        meta = meta or {}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": meta.get("name", "response"),
                "schema": adapted_schema,
                "strict": bool(meta.get("strict", True)),
            },
        }

    def _normalize_tool_output(self, item: Any):
        """
        Convert provider-native tool output into normalized tool call/result parts.

        Currently supports:
            - ImageGenerationCall -> (LLMToolCall, ToolResultContent)
        """
        with service_span_sync(
                "simcore.tools.handle_output",
                attributes={
                    "simcore.provider_name": self.name,
                    "simcore.output.type": type(item).__name__,
                },
        ):
            if isinstance(item, ImageGenerationCall):
                call_id = getattr(item, "id", None) or str(uuid4())
                b64 = getattr(item, "result", None)
                mime = getattr(item, "mime_type", None) or "image/png"
                return (
                    LLMToolCall(call_id=call_id, name="image_generation", arguments={}),
                    ToolResultContent(call_id=call_id, mime_type=mime, data_b64=b64),
                )
            return None

    async def call(self, req: Request, timeout: float | None = None) -> Response:
        """
        Execute a non-streaming request against the OpenAI Responses API.

        Args:
            req: Normalized request DTO (input, tools, schema, etc.).
            timeout: Optional per-call timeout; falls back to `self.timeout_s`.

        Returns:
            Response normalized via the BaseProvider adaptation pipeline.
        """
        logger.debug("provider '%s':: received request call", self.name)

        async with service_span(
                "simcore.client.call",
                attributes={
                    "simcore.provider_name": self.name,
                    "simcore.client_name": getattr(self, "name", self.__class__.__name__),
                    "simcore.model": req.model or self.default_model or "<unspecified>",
                    "simcore.stream": bool(getattr(req, "stream", False)),
                    "simcore.request.correlation_id": str(getattr(req, "correlation_id", "")) or None,
                    "simcore.codec": getattr(req, "codec", None),
                    **_flatten_context(getattr(req, "context", {}) or {}),
                },
        ):
            # Adapt tools (child span)
            async with service_span("simcore.tools.adapt", attributes={"simcore.provider_name": self.name}):
                native_tools = self._tools_to_provider(req.tools)
                if native_tools:
                    logger.debug("provider '%s':: adapted tools: %s", self.name, native_tools)
                else:
                    logger.debug("provider '%s':: no tools to adapt", self.name)

            # Serialize input input (child span)
            async with service_span("simcore.prompt.serialize",
                                    attributes={"simcore.msg.count": len(req.input or [])}):
                input_ = [m.model_dump(include={"role", "content"}, exclude_none=True) for m in req.input]

            model_name = req.model or self.default_model or "gpt-4o-mini"

            # Provider request (child span)
            async with service_span("simcore.provider.send", attributes={"simcore.provider_name": self.name}):
                resp: OpenAIResponse = await self._client.responses.create(
                    model=model_name,
                    input=input_,
                    previous_response_id=req.previous_response_id or NOT_GIVEN,
                    tools=native_tools or NOT_GIVEN,
                    tool_choice=req.tool_choice or NOT_GIVEN,
                    max_output_tokens=req.max_output_tokens or NOT_GIVEN,
                    timeout=timeout or self.timeout_s or NOT_GIVEN,
                    text=req.response_schema_json or NOT_GIVEN,
                )

            logger.debug(
                "provider '%s':: received response\n(response (pre-adapt):\t%s)",
                self.name,
                str(resp)[:1000],
            )

            # Normalize/Adapt (core BaseProvider handles nested spans for normalize)
            return self.adapt_response(resp, output_schema_cls=req.response_schema)

    async def stream(self, req: Request):  # pragma: no cover - streaming not implemented yet
        """
        Execute a streaming request against the OpenAI Responses API.

        Note:
            Streaming is not yet implemented and will raise ProviderError.
        """
        async with service_span(
                "simcore.client.stream",
                attributes={
                    "simcore.provider_name": self.name,
                    "simcore.client_name": getattr(self, "name", self.__class__.__name__),
                    "simcore.model": req.model or self.default_model or "<unspecified>",
                    "simcore.stream": True,
                    "simcore.request.correlation_id": str(getattr(req, "correlation_id", "")) or None,
                    "simcore.codec": getattr(req, "codec", None),
                    **_flatten_context(getattr(req, "context", {}) or {}),
                },
        ) as span:
            try:
                # When streaming is implemented, emit per-chunk events here, e.g.:
                # span.add_event("simcore.client.stream_chunk", {"type": "input_text", "bytes": len(delta)})
                pass
            finally:
                # For now, note unimplemented to aid observability
                try:
                    span.add_event("simcore.client.stream.unimplemented", {"reason": "not yet implemented"})
                except Exception:
                    pass
            raise ProviderError("OpenAIProvider.stream is not implemented yet")

    # --- BaseProvider hook implementations ---------------------------------
    def _extract_text(self, resp: OpenAIResponse) -> str | None:
        """Return the primary text output from the OpenAI response, if present."""
        return getattr(resp, "output_text", None)

    def _extract_outputs(self, resp: OpenAIResponse):
        """Return iterable of native output items (images, tools, etc.)."""
        return getattr(resp, "output", []) or []

    def _is_image_output(self, item: Any) -> bool:
        """Return True if the given item represents an image generation result."""
        return isinstance(item, ImageGenerationCall)

    # def _build_attachment(self, item: Any) -> AttachmentItem | None:
    #     ...

    def _extract_usage(self, resp: OpenAIResponse) -> dict:
        """
        Extract normalized token usage information from the response, if available.

        Returns:
            A dictionary with input/output/total tokens and optional details.
        """
        usage = getattr(resp, "usage", None)
        if not usage:
            return {}

        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)

        itd = getattr(usage, "input_tokens_details", None)
        otd = getattr(usage, "output_tokens_details", None)

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "input_tokens_details": getattr(itd, "cached_tokens", None) if itd else None,
            "output_tokens_details": getattr(otd, "reasoning_tokens", None) if otd else None,
        }

    def _extract_provider_meta(self, resp: OpenAIResponse) -> dict:
        """
        Build provider-specific metadata for diagnostics.

        Includes model name, response id, and (in DEBUG) the full provider response dump.
        """
        meta = {
            "model": getattr(resp, "model", None),
            "provider": self.name,
            "provider_response_id": getattr(resp, "id", None),
        }
        if logger.isEnabledFor(logging.DEBUG):
            try:
                meta["provider_response"] = resp.model_dump()
            except Exception:
                meta["provider_response"] = None
        return meta
