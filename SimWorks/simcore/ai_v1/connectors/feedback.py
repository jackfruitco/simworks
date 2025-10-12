# simcore/ai_v1/connectors/feedback.py
from __future__ import annotations

import logging

from chatlab.models import Message
from chatlab.utils import broadcast_event, broadcast_message
from simcore.ai_v1 import PromptEngine, get_ai_client
from simcore.ai_v1.promptkit import Prompt
from simcore.ai_v1.prompts import HotwashInitialSection, HotwashContinuationSection
from simcore.ai_v1.schemas import StrictOutputSchema, LLMRequest, MessageItem, ToolItem, LLMResponse
from simcore.ai_v1.schemas.output import OutputFeedbackSchema, InstructorReplyOutputSchema
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

    # Build prompt
    p: Prompt = await PromptEngine.abuild_from(
        HotwashInitialSection
    )

    # Build LLM message list for request
    # messages: list[NormalizedAIMessage] = [
    messages: list[MessageItem] = [
        MessageItem(role="developer", content=p.instruction or ""),
        MessageItem(role="user", content=p.message or ""),
    ]

    # Filter out any messages with empty or None content before sending to the LLM
    messages = [m for m in messages if m.content not in (None, "")]

    # req = NormalizedAIRequest(
    req = LLMRequest(
        messages=messages,
        schema_cls=schema_cls,
        previous_response_id=previous_response_id,
        tools=tools or [],
        metadata={
            "use_case": f"simcore:instructor_{rtype}",
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


async def generate_hotwash_response(
        *,
        simulation_id: int,
        rtype: str = "hotwash_response",
        user_msg: Message | int = None,
        as_dict: bool = True,
        tools: list[ToolItem] | None = None,
        timeout: float | None = None,
        **kwargs,
) -> LLMResponse:
    """Generate the feedback message for the hotwash section."""
    client = get_ai_client()
    simulation_ = await Simulation.aresolve(simulation_id)
    previous_response_id = await simulation_.aget_previous_response_id()
    schema_cls = InstructorReplyOutputSchema

    # Get Message instance from user_msg FK and attach to prompt
    if user_msg and not isinstance(user_msg, Message):
        try:
            user_msg = await Message.objects.aget(id=user_msg)
        except Message.DoesNotExist:
            logger.warning(f"No message found with pk={user_msg} -- skipping")
            user_msg = None

    # Build prompt
    # Add user_msg.content to prompt if provided, otherwise
    # Prompt will be generated with generic "I'd like to discuss more." message
    # TODO update Prompt to use user_msg.content as P.message if provided
    p: Prompt = await PromptEngine.abuild_from(
        HotwashContinuationSection,
        user_msg=user_msg,
    )

    # Build LLM message list for request
    # messages: list[NormalizedAIMessage] = [
    messages: list[MessageItem] = [
        MessageItem(role="developer", content=p.instruction or ""),
        MessageItem(role="user", content=p.message or ""),
    ]

    # Filter out any messages with empty or None content before sending to the LLM
    messages = [m for m in messages if m.content not in (None, "")]

    req = LLMRequest(
        messages=messages,
        schema_cls=schema_cls,
        previous_response_id=previous_response_id,
        tools=tools or [],
        metadata={
            "use_case": f"simcore:instructor_{rtype}",
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

    # Uses the same structure as patient responses (different from initial feedback)
    for m in resp.messages:
        try:
            await broadcast_message(m.db_pk, display_name="Stitch")
        except Exception as e:
            logger.exception(
                "failed to broadcast message with pk %r: #r", m.db_pk, e
            )
    return resp.model_dump() if as_dict else resp
