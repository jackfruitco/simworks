# simcore/ai/connectors/feedback.py
from __future__ import annotations

import logging

from chatlab.utils import broadcast_event
from simcore.ai import PromptEngine, get_ai_client
from simcore.ai.promptkit import Prompt
from simcore.ai.prompts import FeedbackEndexSection
from simcore.ai.schemas import StrictOutputSchema, LLMRequest, MessageItem, ToolItem, LLMResponse
from simcore.ai.schemas.output import OutputFeedbackSchema
from simcore.models import Simulation, SimulationFeedback

logger = logging.getLogger(__name__)


async def generate_endex_feedback(
        *,
        simulation_id: int,
        rtype: str = "feedback_endex",
        as_dict: bool = True,
        tools: list[ToolItem] | None = None,
        timeout: float | None = None,
        **kwargs,
) -> LLMResponse:
    """Generate the feedback message for the endex section."""
    client = get_ai_client()
    simulation_ = await Simulation.aresolve(simulation_id)
    previous_response_id = await simulation_.aget_previous_response_id()
    schema_cls = OutputFeedbackSchema

    # Build prompt with submitted orders
    p: Prompt = await PromptEngine.abuild_from(
        FeedbackEndexSection
    )

    # Build LLM message list for request
    # messages: list[NormalizedAIMessage] = [
    messages: list[MessageItem] = [
        MessageItem(role="developer", content=p.instruction or ""),
        MessageItem(role="user", content=p.message or ""),
    ]

    for m in messages:
        if m.content is None or m.content == "":
            messages.pop(messages.index(m))

    # req = NormalizedAIRequest(
    req = LLMRequest(
        messages=messages,
        schema_cls=schema_cls,
        previous_response_id=previous_response_id,
        tools=tools or [],
        metadata={
            "use_case": f"simcore:patient_{rtype}",
            "simulation_id": simulation_.id,
        },
    )

    # add kwargs to request if matching key found on NormalizedAIRequest DTO
    for k, v in kwargs.items():
        try:
            setattr(req, k, v)
        except AttributeError:
            logger.warning(f"received kwarg `{k}`, but no matching key found on {req.__class__.__name__} -- skipping")

    resp: LLMResponse = await client.send_request(req, simulation=simulation_, timeout=timeout)

    # No need to broadcast individual objects; this is fetched via HTMX-GET once the event is received
    try:
        await broadcast_event(
            __type="simulation.feedback_created",
            __simulation=simulation_,
        )

    except Exception as e:
        logger.error(f"Failed to broadcast: {e}")