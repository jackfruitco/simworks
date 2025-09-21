# chatlab/ai/connectors/patient_responses.py
import logging

from chatlab.ai.schema import PatientInitialOutputSchema
from chatlab.utils import broadcast_message
from simcore.ai import (
    get_ai_client,
    get_default_model,
)
from simcore.ai.schemas.normalized_types import NormalizedAIMessage, NormalizedAIRequest, NormalizedAIResponse
from simcore.models import Simulation

logger = logging.getLogger(__name__)


async def generate_patient_initial(simulation_id: int) -> dict:
    """Generate initial introduction message for the patient in the ChatLab Session.

    :param simulation_id: The simulation ID.
    :type simulation_id: int

    :param user_msg: The user's initial message.
    :type user_msg: str

    :return: A dictionary containing the initial message and usage information.
    :rtype: dict
    """
    logger.debug(f"connector 'generate_patient_initial' called...")

    # Get parameters
    _client = get_ai_client()
    _simulation = await Simulation.aresolve(simulation_id)
    _schema_cls = PatientInitialOutputSchema
    _model = get_default_model()

    # Build message payload
    _messages_out: list[NormalizedAIMessage] = [
        NormalizedAIMessage(
            # TODO add Sim patient name to prompt instruction
            role="developer", content=_simulation.prompt_instruction
        ),
        NormalizedAIMessage(
            role="user", content=_simulation.prompt_message or ""
        ),
    ]

    request: NormalizedAIRequest = NormalizedAIRequest(
        model=_model,
        messages=_messages_out,
        schema_cls=_schema_cls,
        metadata={"use_case": "chatlab:patient_initial", "simulation_id": _simulation.id},
    )
    logger.debug(f"... request built: {request}")

    resp: NormalizedAIResponse = await _client.send_request(
        request,
        simulation=_simulation
    )
    logger.debug(f"... response received: {resp}")

    for m in resp.messages:
        await broadcast_message(m.db_pk)

    # TODO weird return type... why not return the NormalizedAIResponse?
    return {
        "text": (resp.messages[-1].content if resp.messages else ""),
        "usage": resp.usage,
        "model": resp.provider_meta.get("model"),
    }


async def generate_patient_response(simulation_id: int, user_msg: str) -> dict:
    client = get_ai_client()
    req = NormalizedAIRequest(
        model=get_default_model(),
        messages=[
            NormalizedAIMessage(role="system", content="You are the patient. Be terse under stress."),
            NormalizedAIMessage(role="user", content=user_msg),
        ],
        metadata={"use_case": "chatlab.patient_response", "simulation_id": simulation_id},
    )
