# simcore/ai/client.py
import logging
from typing import AsyncIterator
from typing import Optional

from simcore.ai.providers.base import ProviderBase
from simcore.ai.providers.openai import OpenAIProvider
from simcore.ai.schemas.normalized_types import NormalizedAIRequest, NormalizedAIResponse, NormalizedStreamChunk

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, provider: ProviderBase = OpenAIProvider):
        self.provider = provider

    async def send_request(
        self,
        req: NormalizedAIRequest,
        *,
        simulation: Optional["Simulation"] = None,
        persist: bool = True,
    ) -> NormalizedAIResponse:
        """
        Send a request to the provider and (optionally) persist normalized DTOs.

        :param req: The normalized provider-agnostic request DTO.
        :param simulation: If provided and `persist` is True, messages/metadata will be saved for this Simulation.
        :param persist: Toggle DB persistence; if False, only returns the DTOs.
        :return: The normalized provider-agnostic response DTO.
        """
        logger.debug(f" client received normalized request:\n(request:\t{req})")
        logger.debug(f" client sending request to provider: {self.provider}")

        resp: NormalizedAIResponse = await self.provider.call(req)

        logger.debug(f" client received normalized response:\n(response:\t{resp})")

        if persist and simulation is not None:
            logger.debug(f" client persisting messages/metadata for simulation {simulation.pk}")
            # Persist messages (if any)
            for msg in getattr(resp, "messages", []) or []:
                await msg.persist(simulation)
            # Persist metadata (if any)
            for meta in getattr(resp, "metadata", []) or []:
                await meta.persist(simulation)
            logger.debug(f" client persisted messages/metadata for `Simulation` id {simulation.pk}")

        logger.debug(f" client finished AI request cycle to provider: {self.provider}")

        return resp

    async def stream_request(self, req: NormalizedAIRequest) -> AsyncIterator[NormalizedStreamChunk]:
        logger.exception("Stream request not implemented")
        raise NotImplementedError

        async for chunk in self.provider.stream(req):
            yield chunk