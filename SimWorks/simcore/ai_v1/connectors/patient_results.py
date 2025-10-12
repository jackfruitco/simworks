# simcore/ai_v1/connectors/patient_results.py
import logging
import warnings
from typing import Type

from chatlab.ai.schemas import PatientResultsOutputSchema
from chatlab.models import Message
from chatlab.utils import broadcast_patient_results
from simcore.ai_v1 import get_ai_client, PromptEngine
from simcore.ai_v1.promptkit import Prompt
from simcore.ai_v1.prompts.sections import PatientResultsSection
from simcore.ai_v1.schemas import StrictOutputSchema, LLMRequest, MessageItem, ToolItem, LLMResponse

from simcore.models import Simulation, LabResult, RadResult

logger = logging.getLogger(__name__)


async def _build_messages_and_schema(
        sim: Simulation, *, rtype: str, user_msg: Message | None
) -> tuple[list[MessageItem], Type[StrictOutputSchema] | None]:
    # TODO consider in future if module grows
    raise NotImplementedError


async def generate_patient_results(
        *,
        simulation_id: int,
        rtype: str = "results",
        user_msg: Message | None = None,
        as_dict: bool = True,
        tools: list[ToolItem] | None = None,
        timeout: float | None = None,
        **kwargs,
) -> LLMResponse | dict:
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
    # messages: list[NormalizedAIMessage] = [
    messages: list[MessageItem] = [
        MessageItem(role="developer", content=p.instruction),
        MessageItem(role="user", content=p.message),
    ]

    # req = NormalizedAIRequest(
    req = LLMRequest(
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

    resp: LLMResponse = await client.send_request(req, simulation=sim, timeout=timeout)

    results: list[LabResult | RadResult] = []
    for md in resp.metadata:
        if md.db_pk and md.kind == "lab_result":
            instance_ = await LabResult.objects.aget(pk=md.db_pk)
            results.append(instance_)
        if md.db_pk and md.kind == "rad_result":
            # TODO -- skipping RadResult staging for broadcast until UI can handle this
            logger.warning(
                f"skipping RadResult with pk={md.db_pk}: UI does not support this yet",
                NotImplementedError,
                stacklevel=1
            )

    summary = [
        {
            "id": r.pk,
            "key": getattr(r, "key", None),
            # using the FK id attribute avoids a DB hit
            "simulation_id": getattr(r, "simulation_id", None),
            "model": r.__class__.__name__,
        }
        for r in results
    ]
    logger.debug("results staged for broadcast: %s", summary)

    try:
        # TODO this is ChatLab-specific and not appropriate for simcore.ai_v1 -- move to ChatLab/ai_v1/connectors or move broadcast to ai_v1/utils
        await broadcast_patient_results(results)
    except Exception as e:
        logger.error(f"failed to broadcast results: {e}")

    return resp.model_dump() if as_dict else resp
