import asyncio
import logging
import warnings
from typing import AsyncIterator, Optional

from simcore_ai.providers import BaseProvider
from simcore_ai.providers.exceptions import ProviderCallError
from simcore_ai.tracing import service_span
from simcore_ai.types import LLMResponse, LLMRequest, LLMStreamChunk
from simcore_ai.client.schemas import AIClientConfig

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, provider: BaseProvider, config: Optional[AIClientConfig] = None):
        """
        Initialize an AIClient with a concrete provider and optional runtime config.

        Args:
            provider: Concrete provider implementing BaseProvider (e.g., OpenAIProvider).
            config:   Runtime behavior knobs (retries, timeout, telemetry flags).
        """
        self.provider = provider
        self.config = config or AIClientConfig()

    async def call(
            self,
            req: LLMRequest,
            *,
            timeout: Optional[float] = None,
    ) -> LLMResponse:
        """
        Convenience wrapper that mirrors provider-style `call()`.

        Delegates to `send_request(...)` for backward-compatibility with existing code.
        """
        warnings.warn("AIClient.call() is deprecated; use send_request() instead", DeprecationWarning, stacklevel=2)
        return await self.send_request(req, timeout=timeout)

    async def send_request(
            self,
            req: LLMRequest,
            *,
            timeout: Optional[float] = None,
    ) -> LLMResponse:
        """
        Send a request to the provider and (optionally) persist normalized DTOs.

        :param req: The normalized provider-agnostic request DTO.
        :type req: LLMRequest

        :param timeout: Timeout for the provider call.
            If not specified, uses client config timeout, else provider default.
        :type timeout: Optional[float]

        :return: The normalized provider-agnostic response DTO.
        :rtype: LLMResponse

        :raises Exception: If the provider call fails and raise_on_error=True.
        :raises ProviderCallError: If provider call fails after retries and raise_on_error=True.

        Note:
            If raise_on_error=False, returns a soft-failure empty response with error metadata.
        """
        # Determine effective timeout: explicit arg > client config > provider default
        effective_timeout = (
            timeout
            if timeout is not None
            else (self.config.timeout_s if self.config.timeout_s is not None else getattr(self.provider, "timeout_s", None))
        )

        async with service_span(
                "ai.client.send_request",
                attributes={
                    "ai.provider_name": getattr(self.provider, "name", type(self.provider).__name__),
                    "ai.model": req.model or getattr(self.provider, "default_model", None) or "<unspecified>",
                    "ai.stream": bool(getattr(req, "stream", False)),
                    "ai.timeout": effective_timeout,
                    "ai.provider_key": getattr(self.provider, "provider_key", None),
                    "ai.provider_label": getattr(self.provider, "provider_label", None),
                },
        ):
            logger.debug(f"client received normalized request:\n(request:\t{req})")
            logger.debug(f"client sending request to provider: {self.provider}")

            if not req.model:
                default_model = getattr(self.provider, "default_model", None)
                if default_model:
                    req.model = default_model
                else:
                    logger.debug(
                        "No explicit model provided and provider has no default_model; proceeding without explicit model")

            # Let the provider compile + wrap into a final payload on req.response_format
            try:
                async with service_span("ai.client.build_final_schema"):
                    self.provider.build_final_schema(req)
            except Exception:
                logger.exception(
                    "client failed to build final schema via provider '%s'",
                    getattr(self.provider, "name", self.provider),
                )

            # Client-level retry policy; provider may still influence via exceptions (e.g., 429)
            attempts = max(1, int(getattr(self.config, "max_retries", 1) or 1))
            backoff_ms = 500  # initial backoff; exponential with cap below

            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    async with service_span(
                            "ai.client.provider_call",
                            attributes={
                                "ai.attempt": attempt,
                                "ai.max_attempts": attempts,
                            },
                    ):
                        resp: LLMResponse = await self.provider.call(req, effective_timeout)
                    last_exc = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    # Detect rate-limit to annotate and to choose backoff
                    status = getattr(e, "status_code", None)
                    detail = str(e)
                    is_rl = False
                    try:
                        if (status == 429) or ("rate limit" in detail.lower()):
                            is_rl = True
                    except Exception:
                        pass

                    if is_rl:
                        # Emit a rate-limit span for observability
                        try:
                            # Prefer provider helper if available
                            rec = getattr(self.provider, "record_rate_limit", None)
                            if callable(rec):
                                rec(status_code=status, retry_after_ms=getattr(e, "retry_after", None), detail=detail)
                        except Exception:
                            pass

                    if attempt >= attempts:
                        raise ProviderCallError(f"Provider call failed after {attempts} attempt(s)") from e

                    # Retry with backoff
                    async with service_span(
                            "ai.client.retry",
                            attributes={
                                "ai.attempt": attempt + 1,
                                "ai.backoff_ms": backoff_ms,
                                "ai.error.class": type(e).__name__,
                                "ai.rate_limited": bool(is_rl),
                            },
                    ):
                        await asyncio.sleep(backoff_ms / 1000.0)
                        # Exponential backoff (cap to 10s)
                        backoff_ms = min(int(backoff_ms * 2), 10_000)

            if last_exc is not None:
                if getattr(self.config, "raise_on_error", True):
                    raise ProviderCallError("Provider call failed after retries") from last_exc
                # Best-effort soft failure: return an empty response with error metadata
                logger.warning("AIClient returning soft-failure response due to raise_on_error=False: %s", last_exc)
                return LLMResponse(
                    outputs=None,
                    usage=None,
                    tool_calls=[],
                    provider_meta={
                        "provider": getattr(self.provider, "name", type(self.provider).__name__),
                        "error": str(last_exc),
                        "error_class": type(last_exc).__name__,
                    },
                )

            logger.debug(f"client received response:\n(response (post-adapt):\t{resp.model_dump_json()[:500]})")

            logger.debug(
                f"client finished AI request cycle to provider: {self.provider}\n"
                f"(response (post-persist):\t{resp.model_dump_json()[:500]})"
            )

            return resp

    async def stream_request(self, req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Pass-through streaming; providers may yield LLMStreamChunk deltas."""
        async with service_span(
                "ai.client.stream_request",
                attributes={
                    "ai.provider_name": getattr(self.provider, "name", type(self.provider).__name__),
                    "ai.model": req.model or getattr(self.provider, "default_model", None) or "<unspecified>",
                    "ai.stream": True,
                    "ai.provider_key": getattr(self.provider, "provider_key", None),
                    "ai.provider_label": getattr(self.provider, "provider_label", None),
                },
        ):
            async for chunk in self.provider.stream(req):
                yield chunk
