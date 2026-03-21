# simcore/orca/schemas/feedback.py
"""
Feedback schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

from pydantic import BaseModel, ConfigDict, Field

from apps.common.outbox import event_types as outbox_events
from apps.simcore.orca.persist.feedback_block import (
    persist_continuation_feedback_block,
    persist_initial_feedback_block,
)

from .output_items import InitialFeedbackBlock, LLMConditionsCheckItem


class GenerateInitialSimulationFeedback(BaseModel):
    """Initial user feedback (hotwash) schema.

    **Persistence** (declarative):
    - metadata → multiple SimulationFeedback records via ``persist_feedback_block``
    - llm_conditions_check → NOT PERSISTED

    **WebSocket Broadcasting**:
    - Broadcasts ``feedback.item.created`` events via outbox pattern in ``post_persist``
    - Event payload includes feedback_id, key, value for each feedback item
    - Enables real-time UI updates when feedback is generated
    """

    model_config = ConfigDict(extra="forbid")

    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ..., description="Internal workflow conditions"
    )
    metadata: InitialFeedbackBlock = Field(..., description="Feedback data block")

    __persist__ = {"metadata": persist_initial_feedback_block}
    __persist_primary__ = "metadata"

    async def post_persist(self, results, context):
        """Broadcast feedback creation to WebSocket clients.

        Creates outbox events for each SimulationFeedback object that was
        persisted, allowing connected clients to receive real-time notifications
        when feedback is generated.

        The events are delivered via the outbox pattern for reliability:
        1. Events created atomically with domain changes
        2. Drain worker delivers to WebSocket channel layer
        3. Clients receive standardized envelope with event_id for deduplication

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.

        WebSocket Event Structure:
            {
                "event_id": "uuid",
                "event_type": "feedback.item.created",
                "created_at": "2026-02-22T...",
                "simulation_id": "123",
                "correlation_id": "abc-xyz",
                "payload": {
                    "feedback_id": 456,
                    "key": "hotwash_correct_diagnosis",
                    "value": "true"
                }
            }
        """
        from apps.common.outbox.helpers import broadcast_domain_objects

        await broadcast_domain_objects(
            event_type=outbox_events.FEEDBACK_CREATED,
            objects=results.get("metadata", []),
            context=context,
            payload_builder=lambda fb: {
                "feedback_id": fb.id,
                "key": fb.key,
                "value": fb.value,
            },
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
    """Structured continuation feedback response schema."""

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
        """Broadcast continuation feedback updates to clients."""
        from apps.common.outbox.helpers import broadcast_domain_objects

        await broadcast_domain_objects(
            event_type=outbox_events.FEEDBACK_CREATED,
            objects=results.get("metadata", []),
            context=context,
            payload_builder=lambda fb: {
                "feedback_id": fb.id,
                "key": fb.key,
                "value": fb.value,
            },
        )
