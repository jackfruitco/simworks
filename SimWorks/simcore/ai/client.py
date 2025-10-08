import logging
from typing import AsyncIterator, Optional

from simcore.ai import get_default_model
from simcore.ai.providers.base import ProviderBase
from simcore.ai.schemas import LLMResponse, LLMRequest, StreamChunk
from simcore.ai.utils import persist_all

logger = logging.getLogger(__name__)

from simcore.models import Simulation


class AIClient:
    def __init__(self, provider: ProviderBase):
        self.provider = provider

    async def send_request(
            self,
            req: LLMRequest,
            *,
            simulation: Optional[Simulation] = None,
            timeout: Optional[float] = None,
            persist: bool = True,
    ) -> LLMResponse:
        """
        Send a request to the provider and (optionally) persist normalized DTOs.

        :param req: The normalized provider-agnostic request DTO.
        :type req: NormalizedAIRequest

        :param simulation: If provided and `persist` is True, messages/metadata will be saved for this Simulation.
        :type simulation: Optional[Simulation]

        :param persist: Toggle DB persistence; if False, only returns the DTOs.
        :type persist: bool

        :param timeout: Timeout for the provider call.
        :type timeout: Optional[float]

        :return: The normalized provider-agnostic response DTO.
        :rtype: NormalizedAIResponse

        :raises Exception: If the provider call fails.
        """
        logger.debug(f"client received normalized request:\n(request:\t{req})")
        logger.debug(f"client sending request to provider: {self.provider}")

        if not req.model:
            req.model = get_default_model()

        if self.provider.has_schema_overrides():
            logger.debug(f"client applying schema overrides for provider {self.provider}")
            override_cls = self.provider.apply_schema_overrides(req.schema_cls)
            logger.debug(
                f"client applied schema overrides for provider {self.provider}: {override_cls}"
            )
            req.schema_cls = override_cls

        # Forward request to provider
        resp: LLMResponse = await self.provider.call(req, timeout)

        logger.debug(f"client received response:\n(response (post-adapt):\t{resp.model_dump_json()[:500]})")

        if persist and simulation is not None:
            logger.debug(f"client persisting response for simulation {simulation.pk}")
            # await resp.persist_full_response(simulation)
            await persist_all(resp, simulation)
            logger.debug(f"client persisted response for `Simulation` id {simulation.pk}")

        logger.debug(
            f"client finished AI request cycle to provider: {self.provider}\n"
            f"(response (post-persist):\t{resp.model_dump_json()[:500]})"
        )

        return resp

    async def stream_request(self, req: LLMRequest) -> AsyncIterator[StreamChunk]:
        logger.exception("Stream request not implemented")
        raise NotImplementedError

        async for chunk in self.provider.stream(req):
            yield chunk
