# orchestrai/client/client.py
import asyncio
import inspect
import logging
from typing import AsyncIterator

from contextlib import asynccontextmanager

from .schemas import OrcaClientConfig
from ..components.providerkit import BaseProvider
from ..components.providerkit.exceptions import ProviderCallError
from ..tracing import service_span
from ..types import Response, Request, StreamChunk

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _noop_span(*args, **kwargs):
    yield


class OrcaClient:
    def __init__(self, provider: BaseProvider, config: OrcaClientConfig | None = None):
        """
        Initialize an OrcaClient with a concrete backend and optional runtime config.

        Args:
            provider: Concrete backend implementing BaseProvider (e.g., OpenAIResponsesProvider).
            config:   Runtime behavior knobs (retries, timeout, telemetry flags).
        """
        self.provider = provider
        self.config = config or OrcaClientConfig()

    async def send_request(
            self,
            req: Request,
            *,
            timeout: float | None = None,
    ) -> Response:
        """
        Send a request to the backend and (optionally) persist normalized DTOs.

        :param req: The normalized backend-agnostic request DTO.
        :type req: Request

        :param timeout: Timeout for the backend call.
            If not specified, uses client config timeout, else backend default.
        :type timeout: Optional[float]

        :return: The normalized backend-agnostic response DTO.
        :rtype: Response

        :raises Exception: If the backend call fails and raise_on_error=True.
        :raises ProviderCallError: If backend call fails after retries and raise_on_error=True.

        Note:
            If raise_on_error=False, returns a soft-failure empty response with error metadata.
        """
        if timeout is not None:
            effective_timeout = timeout
        elif self.config.timeout_s is not None:
            effective_timeout = self.config.timeout_s
        else:
            effective_timeout = getattr(self.provider, "timeout_s", None)

        span_factory = service_span if getattr(self.config, "telemetry_enabled", True) else _noop_span

        async with span_factory(
                "simcore.client.send_request",
                attributes={
                    "simcore.provider_name": getattr(self.provider, "name", type(self.provider).__name__),
                    "simcore.model": req.model or getattr(self.provider, "default_model", None) or "<unspecified>",
                    "simcore.stream": bool(getattr(req, "stream", False)),
                    "simcore.timeout": effective_timeout,
                    "simcore.provider_key": getattr(self.provider, "provider_key", None),
                    "simcore.provider_label": getattr(self.provider, "provider_label", None),
                },
        ):
            if getattr(self.config, "log_prompts", False):
                logger.debug("client received normalized request:\n(request:\t%r)", req)
                logger.debug("client sending request to backend: %r", self.provider)

            if not req.model:
                default_model = getattr(self.provider, "default_model", None)
                if default_model:
                    req.model = default_model
                else:
                    logger.debug(
                        "No explicit model provided and backend has no default_model; proceeding without explicit model")

            # TODO: remove legacy adapter integration. Now in codec.encode
            # # Let the backend compile + wrap into a final payload on req.response_schema_json
            # try:
            #     async with service_span("simcore.client.build_final_schema"):
            #         self.backend.build_final_schema(req)
            # except Exception:
            #     logger.exception(
            #         "client failed to build final schema via backend '%s'",
            #         getattr(self.backend, "name", self.backend),
            #     )

            attempts = max(1, int(self.config.max_retries or 1))
            INITIAL_BACKOFF_MS = 500
            MAX_BACKOFF_MS = 10_000
            backoff_ms = INITIAL_BACKOFF_MS

            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    async with span_factory(
                            "simcore.client.provider_call",
                            attributes={
                                "simcore.attempt": attempt,
                                "simcore.max_attempts": attempts,
                            },
                    ):
                        if inspect.iscoroutinefunction(self.provider.call):
                            resp: Response = await self.provider.call(req, effective_timeout)
                        else:
                            # Provider is sync; run in a worker thread to avoid blocking the event loop
                            resp: Response = await asyncio.to_thread(self.provider.call, req, effective_timeout)
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
                            # Prefer backend helper if available
                            rec = getattr(self.provider, "record_rate_limit", None)
                            if callable(rec):
                                rec(status_code=status, retry_after_ms=getattr(e, "retry_after", None), detail=detail)
                        except Exception:
                            pass

                    if attempt >= attempts:
                        raise ProviderCallError(f"Provider call failed after {attempts} attempt(s)") from e

                    # Retry with backoff
                    async with span_factory(
                            "simcore.client.retry",
                            attributes={
                                "simcore.attempt": attempt + 1,
                                "simcore.backoff_ms": backoff_ms,
                                "simcore.error.class": type(e).__name__,
                                "simcore.rate_limited": bool(is_rl),
                            },
                    ):
                        await asyncio.sleep(backoff_ms / 1000.0)
                        # Exponential backoff (cap to 10s)
                        backoff_ms = min(int(backoff_ms * 2), MAX_BACKOFF_MS)

            if last_exc is not None:
                if getattr(self.config, "raise_on_error", True):
                    raise ProviderCallError("Provider call failed after retries") from last_exc
                # Best-effort soft failure: return an empty response with error metadata
                logger.warning("OrcaClient returning soft-failure response due to raise_on_error=False: %s", last_exc)
                return Response(
                    output=[],
                    usage=None,
                    tool_calls=[],
                    provider_meta={
                        "backend": getattr(self.provider, "name", type(self.provider).__name__),
                        "error": str(last_exc),
                        "error_class": type(last_exc).__name__,
                    },
                )

            if getattr(self.config, "log_prompts", False):
                logger.debug(f"client received response:\n(response (post-adapt):\t{resp.model_dump_json()[:500]})")

                logger.debug(
                    f"client finished AI request cycle to backend: {self.provider}\n"
                    f"(response (post-persist):\t{resp.model_dump_json()[:500]})"
                )

            return resp

    async def stream_request(self, req: Request) -> AsyncIterator[StreamChunk]:
        """Pass-through streaming; providers may yield StreamChunk deltas."""
        span_factory = service_span if getattr(self.config, "telemetry_enabled", True) else _noop_span
        async with span_factory(
                "simcore.client.stream_request",
                attributes={
                    "simcore.provider_name": getattr(self.provider, "name", type(self.provider).__name__),
                    "simcore.model": req.model or getattr(self.provider, "default_model", None) or "<unspecified>",
                    "simcore.stream": True,
                    "simcore.provider_key": getattr(self.provider, "provider_key", None),
                    "simcore.provider_label": getattr(self.provider, "provider_label", None),
                },
        ):
            if not hasattr(self.provider, "stream") or not inspect.iscoroutinefunction(
                    getattr(self.provider, "stream")):
                raise ProviderCallError("Provider does not support async streaming via 'stream(req)'.")
            # Note: streaming is a one-shot operation; we do not apply client-level retries here.
            async for chunk in self.provider.stream(req):
                yield chunk
