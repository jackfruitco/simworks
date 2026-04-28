# simcore/orca/schemas/feedback.py
"""
Feedback (initial + continuation) schemas for Pydantic AI.

These are plain Pydantic models used as ``result_type`` for Pydantic AI
agents. Persistence writes to the ``apps.assessments`` app via the
declarative ``__persist__`` dict; ``post_persist`` broadcasts a single
``assessment.item.created`` event per produced :class:`Assessment`.
"""

from pydantic import BaseModel, ConfigDict, Field

from apps.assessments.services.persistence import (
    persist_continuation_feedback_block,
    persist_initial_feedback_block,
)
from apps.common.outbox import event_types as outbox_events

from .output_items import InitialFeedbackBlock, LLMConditionsCheckItem


def _assessment_payload(assessment) -> dict:
    """Build the WebSocket payload for an ``assessment.item.created`` event.

    Returns minimal, JSON-friendly fields. Clients can fetch the full
    assessment via the simulation tools API for richer rendering.
    """
    return {
        "assessment_id": str(assessment.id),
        "rubric_slug": assessment.rubric.slug,
        "rubric_version": assessment.rubric.version,
        "assessment_type": assessment.assessment_type,
        "lab_type": assessment.lab_type,
        "overall_score": (
            float(assessment.overall_score) if assessment.overall_score is not None else None
        ),
    }


class GenerateInitialSimulationFeedback(BaseModel):
    """Initial post-simulation assessment schema.

    **Persistence** (declarative):
    - ``metadata`` → one :class:`Assessment` (assessment_type=
      ``initial_feedback``) plus three :class:`AssessmentCriterionScore`
      rows plus one :class:`AssessmentSource` (role=``primary``,
      source_type=``simulation``) via ``persist_initial_feedback_block``.
    - ``llm_conditions_check`` → not persisted.

    **WebSocket broadcasting**:
    - One ``assessment.item.created`` event per produced Assessment.
    - Payload: ``assessment_id``, ``rubric_slug``, ``rubric_version``,
      ``assessment_type``, ``lab_type``, ``overall_score``.
    """

    model_config = ConfigDict(extra="forbid")

    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ..., description="Internal workflow conditions"
    )
    metadata: InitialFeedbackBlock = Field(..., description="Feedback data block")

    __persist__ = {"metadata": persist_initial_feedback_block}
    __persist_primary__ = "metadata"

    async def post_persist(self, results, context):
        """Broadcast assessment creation to WebSocket clients."""
        from apps.common.outbox.helpers import broadcast_domain_objects

        await broadcast_domain_objects(
            event_type=outbox_events.ASSESSMENT_CREATED,
            objects=results.get("metadata", []),
            context=context,
            payload_builder=_assessment_payload,
        )


class FeedbackContinuationBlock(BaseModel):
    """Structured continuation feedback payload for learner follow-up Q&A."""

    model_config = ConfigDict(extra="forbid")

    direct_answer: str = Field(
        ...,
        min_length=1,
        description="Direct answer to the learner's follow-up question",
    )


class GenerateFeedbackContinuationResponse(BaseModel):
    """Structured continuation feedback response schema.

    Persistence creates a *separate* :class:`Assessment` of
    ``assessment_type="continuation_feedback"`` linked back to the
    initial assessment via an :class:`AssessmentSource` row with
    ``role=generated_from``.
    """

    model_config = ConfigDict(extra="forbid")

    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Internal workflow conditions",
    )
    metadata: FeedbackContinuationBlock = Field(
        ...,
        description="Continuation Q&A feedback block",
    )

    __persist__ = {"metadata": persist_continuation_feedback_block}
    __persist_primary__ = "metadata"

    async def post_persist(self, results, context):
        """Broadcast assessment creation for the continuation row."""
        from apps.common.outbox.helpers import broadcast_domain_objects

        await broadcast_domain_objects(
            event_type=outbox_events.ASSESSMENT_CREATED,
            objects=results.get("metadata", []),
            context=context,
            payload_builder=_assessment_payload,
        )
