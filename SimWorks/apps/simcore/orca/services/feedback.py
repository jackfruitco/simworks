# simcore/orca/services/feedback.py
"""Feedback AI services for simulation using class-based instructions."""

import logging
from typing import ClassVar

from asgiref.sync import sync_to_async

from apps.common.utils import Formatter
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca

from ..mixins import FeedbackMixin  # Identity mixin for component discovery

logger = logging.getLogger(__name__)


@orca.service
class GenerateInitialFeedback(PreviousResponseMixin, FeedbackMixin, DjangoBaseService):
    """Generate the initial patient feedback using Pydantic AI."""

    instruction_refs: ClassVar[list[str]] = [
        "simcore.feedback.FeedbackInitialInstruction",
        "common.feedback.FeedbackEducatorInstruction",
        "common.shared.MedicalAccuracyInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.simcore.orca.schemas import GenerateInitialSimulationFeedback as _Schema

    response_schema = _Schema

    async def _aprepare_context(self) -> None:
        """Ground feedback in the canonical simulation transcript.

        Provider response continuity (PreviousResponseMixin) is supplemental;
        transcript is the canonical ground truth for feedback grounding.
        """
        # Chain mixin: lets PreviousResponseMixin set previous_response_id as supplement
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        # Respect explicit caller-provided user_message
        if self.context.get("user_message"):
            return

        simulation_id = self.context.get("simulation_id")

        try:
            from apps.simcore.models import Simulation

            sim = await Simulation.objects.aget(pk=simulation_id)
        except Exception as exc:
            logger.warning(
                "[feedback] simulation %s not found, transcript unavailable: %s",
                simulation_id,
                exc,
            )
            self.context["user_message"] = (
                "The simulation transcript is unavailable (simulation not found). "
                "State this and provide the most conservative assessment possible."
            )
            return

        history = await sync_to_async(sim.history)()
        messages = [entry for entry in history if entry.get("content")]

        logger.info(
            "[feedback] simulation=%s messages_loaded=%d has_previous_response=%s",
            simulation_id,
            len(messages),
            bool(self.context.get("previous_response_id")),
        )

        transcript = Formatter(messages).render("openai_sim_transcript")
        self.context["transcript"] = transcript

        if not transcript:
            logger.warning(
                "[feedback] simulation=%s transcript is empty, no messages to ground on",
                simulation_id,
            )
            self.context["user_message"] = (
                "The simulation transcript is unavailable or contains no messages. "
                "State this and provide the most conservative assessment possible."
            )
            return

        logger.info(
            "[feedback] simulation=%s transcript_length=%d",
            simulation_id,
            len(transcript),
        )
        self.context["user_message"] = (
            "Evaluate the following completed simulation. "
            "Base your feedback exclusively on this transcript — "
            "do not invent actions, questions, or omissions not present in the record.\n\n"
            f"### Simulation Transcript\n{transcript}"
        )


@orca.service
class GenerateFeedbackContinuationReply(FeedbackMixin, DjangoBaseService):
    """Generate continuation feedback using Pydantic AI."""

    instruction_refs: ClassVar[list[str]] = [
        "simcore.feedback.FeedbackContinuationInstruction",
        "common.feedback.FeedbackEducatorInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.simcore.orca.schemas import GenerateFeedbackContinuationResponse as _Schema

    response_schema = _Schema
