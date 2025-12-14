# orchestrai/providers/openai/openai.py
"""
This module provides an OpenAI Responses API backend implementation for handling
interaction with OpenAI's async APIs and providing normalized abstractions for custom
tool chaining and input/output processing.

The module includes a class `OpenAIResponsesProvider`, which integrates with OpenAI APIs to
facilitate operations such as health checks, execution of non-streaming requests,
and the adaptive normalization of outputs.

Classes:
    - OpenAIResponsesProvider: Manages backend-specific configuration, OpenAI API interaction,
      and tool adapter integration.

"""
import logging
from typing import Any, Literal, Optional, Final

from openai import NOT_GIVEN, AsyncOpenAI
from openai.types.responses import Response as OpenAIResponse, EasyInputMessageParam

from orchestrai.components.providerkit import BaseProvider
from orchestrai.components.providerkit.exceptions import ProviderError
from orchestrai.decorators import backend
from orchestrai.tracing import service_span, service_span_sync, flatten_context as _flatten_context
from orchestrai.types import Request, Response
from .output_adapters import ImageGenerationOutputAdapter
from .tools import OpenAIToolAdapter

logger = logging.getLogger(__name__)

__all__ = ["OpenAIResponsesProvider"]

PROVIDER_NAME: Final[Literal["openai"]] = "openai"
API_SURFACE: Final[Literal["responses"]] = "responses"
API_VERSION: Final[None] = None

@backend(namespace=PROVIDER_NAME, kind=API_SURFACE, name="backend")
class OpenAIResponsesProvider(BaseProvider):
    """OpenAI Responses API backend."""

    def __init__(
            self,
            *,
            alias: str,
            provider: str | None = PROVIDER_NAME,
            api_surface: Literal["responses"] | None = API_SURFACE,
            api_version: Literal[None] | None = API_VERSION,
            api_key: str | None = None,
            base_url: str | None = None,
            default_model: str | None = None,
            model: str | None = None,
            timeout_s: int = 60,
            profile: str | None = None,
            slug: Optional[str] = None,
            description: str | None = None,
            api_key_required: bool | None = None,
            **kwargs: object,
    ) -> None:
        """
        Initialize the OpenAIResponses backend.

        Args:
            alias: Logical backend alias (e.g., "openai:prod").
            api_key: Final API key (may be None if resolved via env by BaseProvider).
            base_url: Optional custom OpenAI endpoint.
            default_model: Default model if the request does not specify one.
            timeout_s: Request timeout in seconds.
            profile: Optional profile label (e.g., "prod", "staging").
            slug: Optional slug override; falls back to alias/identity.
            description: Optional human-readable description.
            api_key_required: Whether this backend requires an API key. If None,
                BaseProvider will resolve from env or class default.
            **kwargs: Additional config passed through to BaseProvider and ignored there.
        """
        # Initialize shared backend configuration first
        super().__init__(
            alias=alias,
            provider=provider,
            api_key_required=api_key_required,
            api_key=api_key,
            description=description,
            slug=slug,
            profile=profile,

            # Identity parts
            namespace=provider or PROVIDER_NAME,
            kind=api_surface or API_SURFACE,
            name="backend",

            **kwargs,
        )

        # Provider-specific configuration
        self.base_url = base_url
        # Allow either 'default_model' or 'model' to set the default
        self.default_model = default_model if default_model is not None else model
        self.timeout_s = timeout_s

        # Underlying OpenAI async client
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_s,
        )

        # Tool + output adapters
        self.set_tool_adapter(OpenAIToolAdapter())
        self._output_adapters = [ImageGenerationOutputAdapter()]

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

    def _normalize_tool_output(self, item: Any):
        """
        Convert backend-native output into normalized tool call/result parts
        using registered output adapters.
        """
        with service_span_sync(
                "simcore.tools.handle_output",
                attributes={
                    "simcore.provider_name": self.provider,
                    "simcore.output.type": type(item).__name__,
                },
        ):
            for adapter in getattr(self, "_output_adapters", []):
                try:
                    result = adapter.adapt(item)
                except Exception:
                    logger.debug(
                        "backend '%s':: output adapter %s failed; skipping",
                        self.provider,
                        type(adapter).__name__,
                        exc_info=True,
                    )
                    continue
                if result is not None:
                    return result
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
        logger.debug("backend '%s':: received request call", self.provider)

        async with service_span(
                "simcore.client.call",
                attributes={
                    "simcore.provider_name": self.provider,
                    "simcore.client_name": getattr(self, "provider", self.__class__.__name__),
                    "simcore.model": req.model or self.default_model or "<unspecified>",
                    "simcore.stream": bool(getattr(req, "stream", False)),
                    "simcore.request.correlation_id": str(getattr(req, "correlation_id", "")) or None,
                    "simcore.codec": getattr(req, "codec", None),
                    **_flatten_context(getattr(req, "context", {}) or {}),
                },
        ):
            # Adapt tools (child span)
            async with service_span("simcore.tools.adapt", attributes={"simcore.provider_name": self.provider}):
                native_tools = self._tools_to_provider(req.tools)
                if native_tools:
                    logger.debug("backend '%s':: adapted tools: %s", self.provider, native_tools)
                else:
                    logger.debug("backend '%s':: no tools to adapt", self.provider)

            # Serialize input input (child span)
            async with service_span("simcore.prompt.serialize",
                                    attributes={"simcore.msg.count": len(req.input or [])}):
                input_ = [m.model_dump(include={"role", "content"}, exclude_none=True) for m in req.input]

            model_name = req.model or self.default_model or "gpt-4o-mini"
            response_format = (
                    getattr(req, "provider_response_format", None)
                    or getattr(req, "response_schema_json", None)
            )

            logger.debug(
                "backend '%s':: call model=%s stream=%s has_response_format=%s",
                self.provider,
                model_name,
                bool(getattr(req, "stream", False)),
                bool(response_format),
            )

            # Provider request (child span)
            async with service_span("simcore.backend.send", attributes={"simcore.provider_name": self.provider}):
                try:
                    span = service_span("simcore.backend.send")
                    if span is not None:
                        span.set_attribute("simcore.model", model_name)
                        span.set_attribute("simcore.request.has_response_format", bool(response_format))
                        span.set_attribute("simcore.request.tools.count", len(native_tools or []))
                except Exception:
                    pass
                resp: OpenAIResponse = await self._client.responses.create(
                    model=model_name,
                    input=input_,
                    previous_response_id=req.previous_response_id or NOT_GIVEN,
                    tools=native_tools or NOT_GIVEN,
                    tool_choice=req.tool_choice or NOT_GIVEN,
                    max_output_tokens=req.max_output_tokens or NOT_GIVEN,
                    timeout=timeout or self.timeout_s or NOT_GIVEN,
                    text=response_format or NOT_GIVEN,
                )

            logger.debug(
                "backend '%s':: received response\n(response (pre-adapt):\t%s)",
                self.provider,
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
                    "simcore.provider_name": self.provider,
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
            raise ProviderError("OpenAIResponsesProvider.stream is not implemented yet")

    # --- BaseProvider hook implementations ---------------------------------
    def _extract_text(self, resp: OpenAIResponse) -> str | None:
        """Return the primary text output from the OpenAI response, if present."""
        return getattr(resp, "output_text", None)

    def _extract_outputs(self, resp: OpenAIResponse):
        """Return iterable of native output items (images, tools, etc.)."""
        return getattr(resp, "output", []) or []

    def _is_image_output(self, item: Any) -> bool:
        """Return True if the given item represents an image generation result."""
        return False  # ImageGenerationCall import removed; image output detection handled by adapters

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
        Build backend-specific metadata for diagnostics.

        Includes model name, response id, and (in DEBUG) the full backend response dump.
        """
        meta = {
            "model": getattr(resp, "model", None),
            "backend": self.provider,
            "provider_response_id": getattr(resp, "id", None),
        }
        if logger.isEnabledFor(logging.DEBUG):
            try:
                meta["provider_response"] = resp.model_dump()
            except Exception:
                meta["provider_response"] = None
        return meta
