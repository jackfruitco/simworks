import json
import logging
from typing import List

from asgiref.sync import sync_to_async

from ChatLab.models import Message
from SimManAI.models import Response
from SimManAI.parser import StructuredOutputParser
from core.utils import get_system_user

logger = logging.getLogger(__name__)


async def process_response(response, simulation, stream=False) -> List[Message]:
    """
    Unified entry point for handling an OpenAI response within a simulation.

    - Saves a Response object (token usage, raw payload)
    - Parses messages and metadata
    - Returns parsed messages for further use

    Args:
        response: The OpenAI response object (assumed Pydantic or dict-compatible)
        simulation: The associated Simulation instance
        stream: Optional flag to indicate streaming response processing

    Returns:
        list of Message instances created via parser
    """
    if stream:
        return await consume_response(response, simulation)

    usage = response.usage or {}
    user = await sync_to_async(lambda: simulation.user)()

    response_obj = await sync_to_async(Response.objects.create)(
        simulation=simulation,
        user=user,
        raw=json.dumps(response.model_dump(), indent=2),
        id=response.id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"[Sim#{simulation.pk}] raw OpenAI output: {response}")
        logger.debug(f"Tokens: input={response_obj.input_tokens}, output={response_obj.output_tokens}")

    system_user = await sync_to_async(get_system_user)()
    parser = StructuredOutputParser(simulation, system_user, response_obj)
    return await parser.parse_output(response.output_text)

async def consume_response(response, simulation, stream=False) -> List[Message]:
    logger.error("SimManAI.consume_response called, but not implemented. Switching to SimManAI.process_response")
    return await process_response(response, simulation, stream=False)