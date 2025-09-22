# chatlab/ai/connectors/patient_responses.py
import logging
from typing import Type

from chatlab.models import Message
from chatlab.utils import broadcast_message
from simcore.ai import get_ai_client
from simcore.ai.schemas import StrictOutputSchema
from simcore.ai.schemas.normalized_types import (
    NormalizedAIMessage, NormalizedAIRequest, NormalizedAIResponse
)
from simcore.models import Simulation

logger = logging.getLogger(__name__)


async def _build_messages_and_schema(
        sim: Simulation, *, rtype: str, user_msg: Message | None
) -> tuple[list[NormalizedAIMessage], Type[StrictOutputSchema]]:
    if rtype == "initial":
        from chatlab.ai.schema import PatientInitialOutputSchema as Schema  # local import avoids cycles
        msgs = [
            # TODO add sim name to prompt
            NormalizedAIMessage(role="developer", content=sim.prompt_instruction),
            NormalizedAIMessage(role="user", content=sim.prompt_message or ""),
        ]
        return msgs, Schema

    if rtype == "reply":
        if not user_msg:
            raise ValueError("user_msg required for rtype='reply'")

        from chatlab.ai.schema import PatientReplyOutputSchema as Schema
        msgs = [NormalizedAIMessage(role="user", content=user_msg.content)]
        return msgs, Schema

    raise ValueError(f"Unknown rtype: {rtype}")


async def _generate_patient_response(
        *, simulation_id: int, rtype: str, user_msg: Message | None, as_dict: bool
) -> NormalizedAIResponse | dict:
    client = get_ai_client()
    sim = await Simulation.aresolve(simulation_id)
    previous_response_id = await sim.aget_previous_response_id()

    messages, schema_cls = await _build_messages_and_schema(
        sim, rtype=rtype, user_msg=user_msg
    )

    req = NormalizedAIRequest(
        messages=messages,
        schema_cls=schema_cls,
        previous_response_id=previous_response_id,
        metadata={
            "use_case": f"chatlab:patient_{rtype}",
            "simulation_id": sim.id,
            "user_msg_pk": getattr(user_msg, "pk", None),
        },
    )
    resp = await client.send_request(req, simulation=sim)

    for m in resp.messages:
        await broadcast_message(m.db_pk)
    return resp.model_dump() if as_dict else resp


# ---------- Public entry points ------------------------------------------------------
async def generate_patient_initial(
        simulation_id: int, *, as_dict: bool = True
) -> NormalizedAIResponse | dict:
    """Generate patient initial response."""
    return await _generate_patient_response(
        simulation_id=simulation_id,
        rtype="initial",
        user_msg=None,
        as_dict=as_dict
    )


async def generate_patient_reply(
        simulation_id: int, user_msg: Message, *, as_dict: bool = True
) -> NormalizedAIResponse | dict:
    """Generate patient reply response."""
    return await _generate_patient_response(
        simulation_id=simulation_id,
        rtype="reply",
        user_msg=user_msg,
        as_dict=as_dict
    )
