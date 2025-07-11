import base64
import inspect
import json
import logging
import uuid

from asgiref.sync import sync_to_async
from chatlab.models import Message
from core.utils import get_system_user
from core.utils import remove_null_keys
from django.core.files.base import ContentFile
from openai.types.responses import Response as OpenAIResponse
from simai.models import Response as SimCoreResponse
from simai.models import ResponseType
from simai.parser import StructuredOutputParser
from simcore.models import LabResult
from simcore.models import RadResult
from simcore.models import SimulationImage

logger = logging.getLogger(__name__)


async def process_response(
    response: OpenAIResponse,
    simulation,
    stream=False,
    response_type=ResponseType.REPLY,
    **kwargs,
) -> list[Message] | list[LabResult] | list[RadResult] | None:
    """
    Unified entry point for handling an OpenAI response within a simulation.

    - Saves a Response object (token usage, raw payload)
    - Parses messages and metadata
    - Returns parsed messages for further use

    Args:
        response: The OpenAI response object (assumed Pydantic or dict-compatible)
        simulation: The associated Simulation instance
        stream: Optional flag to indicate streaming response processing
        response_type: The type response (see .models.ResponseType)

    Returns:
        list of Message instances created via parser
    """
    if stream:
        return await consume_response(response, simulation)

    usage = response.usage or {}
    user = await sync_to_async(lambda: simulation.user)()

    # Build the payload to create a new Response object, then
    # Remove keys with null values and create the Response object
    payload = {
        "type": response_type,
        "simulation": simulation,
        "user": user,
        "raw": response.model_dump_json(),
        "id": getattr(response, "id", str(uuid.uuid4())),
        "input_tokens": usage.input_tokens or None,
        "output_tokens": usage.output_tokens or None,
    }
    if response_type in (ResponseType.REPLY, ResponseType.PATIENT_RESULTS):
        payload["reasoning_tokens"] = (
            usage.output_tokens_details.reasoning_tokens or None
        )

    payload = remove_null_keys(payload)
    response_obj = await SimCoreResponse.objects.acreate(**payload)

    # Get System User & create Parser
    from core.utils import get_or_create_system_user
    system_user = await get_or_create_system_user()

    parser = StructuredOutputParser(
        simulation=simulation,
        system_user=system_user,
        response=response_obj,
        response_type=response_type,
    )

    # Build payload to send it to parser
    payload = {}
    if response_type == ResponseType.MEDIA:
        payload["output"] = response.data
        payload["mime_type"] = kwargs.get("mime_type")
    else:
        payload["output"] = response.output_text

    return await parser.parse_output(**payload)


async def consume_response(
    response, simulation, stream=False, response_type=None
) -> list[Message] | None:
    logger.error(
        "simai.consume_response called, but not implemented. Switching to simai.process_response"
    )
    return await process_response(response, simulation, stream=False)
