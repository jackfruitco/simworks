import logging
from typing import AsyncIterator, Optional

from simcore_ai.providers import BaseProvider
from simcore_ai.types import LLMResponse, LLMRequest, LLMStreamChunk
from simcore_ai.tracing import service_span
from simcore_ai.exceptions import ProviderCallError
import asyncio

logger = logging.getLogger(__name__)



class AIClient:
    def __init__(self, provider: BaseProvider):
        self.provider = provider

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
        :type timeout: Optional[float]

        :return: The normalized provider-agnostic response DTO.
        :rtype: LLMResponse

        :raises Exception: If the provider call fails.
        """
        async with service_span(
            "ai.client.send_request",
            attributes={
                "ai.provider_name": getattr(self.provider, "name", type(self.provider).__name__),
                "ai.model": req.model or getattr(self.provider, "default_model", None) or "<unspecified>",
                "ai.stream": bool(getattr(req, "stream", False)),
                "ai.timeout": timeout if timeout is not None else getattr(self.provider, "timeout_s", None),
            },
        ):
            logger.debug(f"client received normalized request:\n(request:\t{req})")
            logger.debug(f"client sending request to provider: {self.provider}")

            if not req.model:
                default_model = getattr(self.provider, "default_model", None)
                if default_model:
                    req.model = default_model
                else:
                    logger.debug("No explicit model provided and provider has no default_model; proceeding without explicit model")

            # Let the provider compile + wrap into a final payload on req.response_format
            try:
                async with service_span("ai.client.build_final_schema"):
                    self.provider.build_final_schema(req)
            except Exception:
                logger.exception(
                    "client failed to build final schema via provider '%s'",
                    getattr(self.provider, "name", self.provider),
                )

            # Forward request to provider with simple retry/backoff
            attempts = getattr(self.provider, "retry_attempts", 1) or 1
            backoff_ms = getattr(self.provider, "retry_backoff_ms", 500) or 500

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
                        resp: LLMResponse = await self.provider.call(req, timeout)
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
                raise ProviderCallError("Provider call failed after retries") from last_exc

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
            },
        ):
            async for chunk in self.provider.stream(req):
                yield chunk
