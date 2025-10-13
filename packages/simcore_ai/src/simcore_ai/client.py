import logging
from typing import AsyncIterator, Optional

from .providers import BaseProvider
from .types import LLMResponse, LLMRequest, LLMStreamChunk

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
            self.provider.build_final_schema(req)
        except Exception:
            logger.exception(
                "client failed to build final schema via provider '%s'",
                getattr(self.provider, "name", self.provider),
            )

        # Forward request to provider
        resp: LLMResponse = await self.provider.call(req, timeout)

        logger.debug(f"client received response:\n(response (post-adapt):\t{resp.model_dump_json()[:500]})")

        logger.debug(
            f"client finished AI request cycle to provider: {self.provider}\n"
            f"(response (post-persist):\t{resp.model_dump_json()[:500]})"
        )

        return resp

    async def stream_request(self, req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Pass-through streaming; providers may yield LLMStreamChunk deltas."""
        async for chunk in self.provider.stream(req):
            yield chunk
