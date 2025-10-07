# simcore/ai/connectors/feedback.py
from __future__ import annotations

import logging

from chatlab.utils import broadcast_event
from simcore.ai import PromptEngine, get_ai_client
from simcore.ai.promptkit import Prompt
from simcore.ai.prompts import FeedbackEndexSection
from simcore.ai.schemas import StrictOutputSchema, LLMRequest, MessageItem, ToolItem, LLMResponse
from simcore.models import Simulation

logger = logging.getLogger(__name__)


async def generate_endex_feedback(
        *,
        simulation_id: int,
        as_dict: bool = True,
        tools: list[ToolItem] | None = None,
        timeout: float | None = None,
        **kwargs,
) -> LLMResponse:
    """Generate the feedback message for the endex section."""
    client = get_ai_client()
    sim = await Simulation.aresolve(simulation_id)
    previous_response_id = await sim.aget_previous_response_id()
    schema_cls = StrictOutputSchema