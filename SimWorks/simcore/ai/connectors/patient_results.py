# chatlab/ai/connectors/patient_results.py
import logging
from typing import Type

from chatlab.ai.schema import PatientResultsOutputSchema
from chatlab.models import Message
from simcore.ai import get_ai_client, PromptEngine
from simcore.ai.promptkit import Prompt
from simcore.ai.prompts.sections import PatientResultsSection
from simcore.ai.schemas import StrictOutputSchema
from simcore.ai.schemas.normalized_types import (
    NormalizedAIMessage, NormalizedAIRequest, NormalizedAIResponse, NormalizedAITool
)
from simcore.models import Simulation

logger = logging.getLogger(__name__)


async def _build_messages_and_schema(
        sim: Simulation, *, rtype: str, user_msg: Message | None
) -> tuple[list[NormalizedAIMessage], Type[StrictOutputSchema] | None]:
    # TODO consider in future if module grows
    raise NotImplementedError


async def generate_patient_results(
        *,
        simulation_id: int,
        rtype: str = "results",
        user_msg: Message | None = None,
        as_dict: bool = True,
        tools: list[NormalizedAITool] | None = None,
        timeout: float | None = None,
        **kwargs,
) -> NormalizedAIResponse | dict:
    """Generate patient results for a given simulation."""
    client = get_ai_client()
    sim = await Simulation.aresolve(simulation_id)
    previous_response_id = await sim.aget_previous_response_id()
    schema_cls = PatientResultsOutputSchema
    submitted_orders = kwargs.pop('submitted_orders', None)

    if not submitted_orders:
        raise ValueError('No submitted orders found')

    # Build prompt with submitted orders
    p: Prompt = await PromptEngine.abuild_from(
        PatientResultsSection,
        submitted_orders=submitted_orders
    )

    # Build LLM message list for request
    messages: list[NormalizedAIMessage] = [
        NormalizedAIMessage(role="developer", content=p.instruction),
        NormalizedAIMessage(role="user", content=p.message),
    ]

    req = NormalizedAIRequest(
        messages=messages,
        schema_cls=schema_cls,
        previous_response_id=previous_response_id,
        tools=tools or [],
        metadata={
            "use_case": f"simcore:patient_{rtype}",
            "simulation_id": sim.id,
            "submitted_orders": submitted_orders or None,
        },
    )

    # add kwargs to request if matching key found on NormalizedAIRequest DTO
    for k, v in kwargs.items():
        try:
            setattr(req, k, v)
        except AttributeError:
            logger.warning(f"received kwarg `{k}`, but no matching key found on {req.__class__.__name__} -- skipping")

    resp = await client.send_request(req, simulation=sim, timeout=timeout)

    # No broadcast needed; metadata is refreshed via front-end HTMX-refresh once persisted to DB

    return resp.model_dump() if as_dict else resp
