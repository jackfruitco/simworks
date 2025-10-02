# chatlab/ai/connectors/patient_responses.py
import logging
from typing import Type

from chatlab.models import Message
from chatlab.utils import broadcast_message
from core.utils import remove_null_keys
from simcore.ai import get_ai_client
from simcore.ai.schemas import StrictOutputSchema, MessageItem, LLMResponse, LLMRequest, ToolItem
from simcore.ai.schemas.tools import ImageGenerationTool
from simcore.models import Simulation

logger = logging.getLogger(__name__)


async def _build_messages_and_schema(
        sim: Simulation, *, rtype: str, user_msg: Message | None
) -> tuple[list[MessageItem], Type[StrictOutputSchema] | None]:
    match rtype:

        case "initial":
            from chatlab.ai.schemas import PatientInitialOutputSchema as Schema  # local import avoids cycles
            msgs = [
                MessageItem(role="developer", content=sim.prompt_instruction),
                MessageItem(role="user", content=sim.prompt_message or ""),
            ]
            return msgs, Schema

        case "reply":
            if not user_msg:
                raise ValueError("user_msg required for rtype='reply'")

            from chatlab.ai.schemas import PatientReplyOutputSchema as Schema
            msgs = [MessageItem(role="user", content=user_msg.content)]

            return msgs, Schema

        case "image":
            from simcore.ai.promptkit import PromptEngine, Prompt
            from ..prompts import ImageSection

            p: Prompt = await PromptEngine.abuild_from(ImageSection)
            msgs = [
                MessageItem(role="developer", content=p.instruction),
                # MessageItem(role="user", content=p.message),# TODO placeholder if needed; remove if not needed
            ]

            return msgs, None

        case _:
            logger.exception(f"Unknown rtype: {rtype}", ValueError)
            return [], None


async def generate_patient_image(
        simulation_id: int,
        user_msg: Message | int = None,
        *,
        as_dict: bool = True,
        output_format: str = None,
) -> LLMResponse | dict:
    """Generate patient image response."""
    tool_args: dict = {
        "output_format": output_format
    }
    cleaned_args = remove_null_keys(tool_args)

    return await _generate_patient_response(
        simulation_id=simulation_id,
        rtype="image",
        tools=[
            ImageGenerationTool(**cleaned_args),
        ],
        timeout=120.0,
    )


async def _generate_patient_response(
        *,
        simulation_id: int,
        rtype: str,
        user_msg: Message | None = None,
        as_dict: bool = True,
        tools: list[ToolItem] | None = None,
        timeout: float | None = None,
        **kwargs,
) -> LLMResponse | dict:
    """Internal low-level patient response generator method. Defaults return type: dict.

    Args:
        simulation_id (int): The simulation ID.
        rtype: The response type (e.g. "initial", "reply", "image").
        user_msg: The user message (if any).
        as_dict: Whether to return the response as a dict or as a Model instance.
        tools: Optional list of Normalized tools to use in the response.
        kwargs: Additional keyword arguments to pass to the LLMRequest.

    Returns:
        The normalized LLM response.
    """
    client = get_ai_client()
    sim = await Simulation.aresolve(simulation_id)
    previous_response_id = await sim.aget_previous_response_id()
    if user_msg and not isinstance(user_msg, Message):
        try:
            user_msg = await Message.objects.aget(id=user_msg)
        except Message.DoesNotExist:
            logger.warning(f"No message found with pk={user_msg} -- skipping")
            user_msg = None

    messages, schema_cls = await _build_messages_and_schema(
        sim, rtype=rtype, user_msg=user_msg
    )

    if not messages:
        logger.warning("No messages to send -- skipping.")
        return {}

    req = LLMRequest(
        messages=messages,
        schema_cls=schema_cls,
        previous_response_id=previous_response_id,
        tools=tools or [],
        metadata={
            "use_case": f"chatlab:patient_{rtype}",
            "simulation_id": sim.id,
            "user_msg_pk": getattr(user_msg, "pk", None),
        },
    )

    # add kwargs to request if matching key found on NormalizedAIRequest DTO
    for k, v in kwargs.items():
        try:
            setattr(req, k, v)
        except AttributeError:
            logger.warning(f"received kwarg `{k}`, but no matching key found on {req.__class__.__name__} -- skipping")

    resp = await client.send_request(req, simulation=sim, timeout=timeout)

    if getattr(resp, "image_requested", None):
        logger.debug("image requested -- starting image generation.")

        from simcore.ai.tasks.dispatch import acall_connector
        await acall_connector(
            generate_patient_image,
            simulation_id=simulation_id,
            user_msg=user_msg.pk,
        )

    for m in resp.messages:
        await broadcast_message(m.db_pk)
    return resp.model_dump() if as_dict else resp


# ---------- Public entry points ------------------------------------------------------
async def generate_patient_initial(
        simulation_id: int, *, as_dict: bool = True
) -> LLMResponse | dict:
    """Generate patient initial response."""
    return await _generate_patient_response(
        simulation_id=simulation_id,
        rtype="initial",
        user_msg=None,
        as_dict=as_dict
    )


async def generate_patient_reply(
        simulation_id: int, user_msg: Message | int, *, as_dict: bool = True
) -> LLMResponse | dict:
    """Generate patient reply response."""
    return await _generate_patient_response(
        simulation_id=simulation_id,
        rtype="reply",
        user_msg=user_msg,
        as_dict=as_dict
    )
