import asyncio
import base64
import inspect
import json
import logging
import uuid
from typing import Coroutine

from asgiref.sync import sync_to_async
from chatlab.models import Message
from core.utils import get_system_user
from core.utils import remove_null_keys
from django.core.files.base import ContentFile
from openai.types.responses import Response as OpenAIResponse
from simai.models import Response as SimCoreResponse
from simai.models import ResponseType
from simai.parser import StructuredOutputParser
from simai.response_schema import PatientInitialSchema, PatientReplySchema
from simcore.ai.utils.helpers import maybe_coerce_to_schema
from simcore.models import LabResult, Simulation, SimulationMetadata
from simcore.models import RadResult
from simcore.models import SimulationImage

logger = logging.getLogger(__name__)


async def process_response(
    response: OpenAIResponse,
    simulation: Simulation | int,
    stream: bool = False,
    response_type: ResponseType = ResponseType.REPLY,
    **kwargs,
) -> tuple[list[Message], list[SimulationMetadata]] | list[LabResult] | list[RadResult] | None:
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
        Tuple of parsed messages and metadata, or None if streaming is enabled.
    """
    # Ensure streamed responses are consumed instead of processed
    if stream:
        return await consume_response(response, simulation)

    # Resolve Simulation instance to allow int to be provided
    simulation = await Simulation.aresolve(simulation)

    usage = response.usage or {}
    user = await sync_to_async(lambda: simulation.user)()

    # Build the payload to create a new Response object, then
    # Remove keys with null values and create the Response object
    payload = {
        "type": response_type,
        "simulation": simulation,
        "user": user,
        "raw": response.model_dump_json(),
        "id": response.id or str(uuid.uuid4()),
        "input_tokens": usage.input_tokens or None,
        "output_tokens": usage.output_tokens or None,
    }
    if response_type in (ResponseType.REPLY, ResponseType.PATIENT_RESULTS):
        payload["reasoning_tokens"] = (
            usage.output_tokens_details.reasoning_tokens or None
        )

    payload = remove_null_keys(payload)
    response_log_instance = await SimCoreResponse.objects.acreate(**payload)

    # Get System User & create Parser
    from core.utils import aget_or_create_system_user
    system_user = await aget_or_create_system_user()

    parser = StructuredOutputParser(
        simulation=simulation,
        system_user=system_user,
        response=response_log_instance,
        response_type=response_type,
    )

    # Convert output to the Pydantic model schema if exists, otherwise
    # Get combined `output_text` from OpenAIResponse
    output_text = maybe_coerce_to_schema(response, response_type)

    # Build the task list
    # ... Add a task for each "image_generation_call" in output
    # ... Additionally, add a task for the output text
    tasks: list[Coroutine] = [
        *(parser.parse_output(_output, response_type)
          for _output in response.output if _output.type == "image_generation_call"),
        parser.parse_output(output_text, response_type)
    ]

    if logger.isEnabledFor(logging.DEBUG):
        task_list = "".join(f"\t{task}\n" for task in tasks)
        logger.debug(f"Sending {len(tasks)} tasks to output parser:\n{task_list}")

    # Concurrently run parser tasks and add to the resultset
    resultset = await asyncio.gather(*tasks)

    _message_results: list[Message] = []
    _metadata_results: list[SimulationMetadata] = []

    # Flatten resultset
    for messages, metadata in resultset:
        _message_results.extend(messages)
        _metadata_results.extend(metadata)

    return _message_results, _metadata_results


async def consume_response(
    response, simulation, stream=False, response_type=None
) -> list[Message] | None:
    raise NotImplementedError
