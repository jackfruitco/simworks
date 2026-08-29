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


def _scenario_ground_truth_context(simulation_id, sim) -> tuple[str, str, str]:
    diagnosis = (getattr(sim, "diagnosis", None) or "").strip()
    chief_complaint = (getattr(sim, "chief_complaint", None) or "").strip()

    ground_truth_lines = [
        f"Chief complaint: {chief_complaint or 'unavailable'}",
        f"Correct diagnosis: {diagnosis or 'unavailable'}",
    ]

    if not diagnosis or not chief_complaint:
        logger.warning(
            "[feedback] simulation=%s missing persisted ground truth diagnosis=%r chief_complaint=%r",
            simulation_id,
            diagnosis,
            chief_complaint,
        )

    if not diagnosis or not chief_complaint:
        ground_truth_lines.append(
            "Persisted scenario ground truth is incomplete. State this limitation; "
            "do not infer any unavailable authoritative case answer as certain."
        )

    ground_truth = "\n".join(ground_truth_lines)
    return diagnosis, chief_complaint, ground_truth


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
        diagnosis, chief_complaint, ground_truth = _scenario_ground_truth_context(
            simulation_id,
            sim,
        )
        self.context["scenario_diagnosis"] = diagnosis
        self.context["scenario_chief_complaint"] = chief_complaint

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
            "Use the Scenario Ground Truth section as the authoritative case answer. "
            "Use the transcript only to assess what the learner did, asked, missed, or stated. "
            "Do not infer the correct diagnosis from the transcript when persisted ground truth is available. "
            "Do not invent actions, questions, or omissions not present in the record.\n\n"
            f"### Scenario Ground Truth\n{ground_truth}\n\n"
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

    async def _aprepare_context(self) -> None:
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        if self.context.get("user_message"):
            return

        simulation_id = self.context.get("simulation_id")

        try:
            from apps.simcore.models import Simulation

            sim = await Simulation.objects.aget(pk=simulation_id)
        except Exception as exc:
            logger.warning(
                "[feedback] simulation %s not found, ground truth unavailable: %s",
                simulation_id,
                exc,
            )
            return

        diagnosis, chief_complaint, ground_truth = _scenario_ground_truth_context(
            simulation_id,
            sim,
        )
        self.context["scenario_diagnosis"] = diagnosis
        self.context["scenario_chief_complaint"] = chief_complaint

        learner_question = (
            self.context.get("learner_question")
            or self.context.get("question")
            or self.context.get("prompt")
            or ""
        ).strip()
        if not learner_question:
            return

        self.context["user_message"] = (
            "Answer the learner's follow-up feedback question. "
            "Use the Scenario Ground Truth section as the authoritative case answer "
            "when diagnosis or case intent matters. Use the learner question only for "
            "what the learner is asking now.\n\n"
            f"### Scenario Ground Truth\n{ground_truth}\n\n"
            f"### Learner Question\n{learner_question}"
        )
