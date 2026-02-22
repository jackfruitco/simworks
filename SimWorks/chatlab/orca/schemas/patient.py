# chatlab/orca/schemas/patient.py
"""
Patient output schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

import logging

from pydantic import BaseModel, Field, ConfigDict

from orchestrai.types import ResultMessageItem
from simulation.orca.schemas.output_items import LLMConditionsCheckItem
from simulation.orca.schemas.metadata_items import MetadataItem
from .mixins import PatientResponseBaseMixin

logger = logging.getLogger(__name__)


class PatientInitialOutputSchema(PatientResponseBaseMixin):
    """Output for the initial patient response turn.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - metadata → simulation.SimulationMetadata polymorphic models via auto-mapper
    - llm_conditions_check → NOT PERSISTED

    **Metadata Structure**:
    The LLM must generate metadata items with the correct polymorphic structure:
    - ``kind="lab_result"`` → simulation.LabResult
    - ``kind="rad_result"`` → simulation.RadResult
    - ``kind="patient_history"`` → simulation.PatientHistory
    - ``kind="patient_demographics"`` → simulation.PatientDemographics
    - ``kind="generic"`` → simulation.SimulationMetadata (fallback)

    Each item type includes required fields matching the Django model structure.

    **WebSocket Broadcasting**:
    - Broadcasts ``chat.message_created`` events for patient messages
    - Broadcasts ``metadata.created`` events for demographics/history/results
    - Enables real-time UI updates when initial response is generated
    """

    metadata: list[MetadataItem] = Field(
        ...,
        description="Patient demographics and initial metadata (polymorphic structure with 'kind' discriminator)"
    )

    __persist__ = {"metadata": None}  # None = auto-map via item.__orm_model__
    __persist_primary__ = "messages"

    async def post_persist(self, results, context):
        """Broadcast message and metadata creation to WebSocket clients.

        Creates outbox events for:
        1. Message objects (chat.message_created) - patient initial response
        2. Metadata objects (metadata.created) - demographics, history, etc.

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.
        """
        from core.outbox.helpers import broadcast_domain_objects
        from chatlab.models import Message

        # Broadcast messages
        messages = results.get("messages", [])
        if messages:
            await broadcast_domain_objects(
                event_type="chat.message_created",
                objects=messages,
                context=context,
                payload_builder=lambda msg: {
                    "message_id": msg.id,
                    "content": msg.content or "",
                    "role": msg.role,
                    "is_from_ai": msg.is_from_ai,
                    "display_name": msg.display_name or "",
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                },
            )

        # Broadcast metadata
        metadata = results.get("metadata", [])
        if metadata:
            await broadcast_domain_objects(
                event_type="metadata.created",
                objects=metadata,
                context=context,
                payload_builder=lambda meta: {
                    "metadata_id": meta.id,
                    "kind": meta.polymorphic_ctype.model if hasattr(meta, 'polymorphic_ctype') else "generic",
                    "key": meta.key,
                    "value": meta.value,
                },
            )


class PatientReplyOutputSchema(PatientResponseBaseMixin):
    """Output for subsequent patient reply turns.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - image_requested → Persisted to Message.image_requested field via context
    - llm_conditions_check → NOT PERSISTED

    **WebSocket Broadcasting**:
    - Broadcasts ``chat.message_created`` events for patient reply messages
    - Enables real-time UI updates when patient responds
    """

    image_requested: bool = Field(
        ...,
        description="Whether the response references images/scans"
    )

    __persist_primary__ = "messages"

    async def post_persist(self, results, context):
        """Update Message records and broadcast to WebSocket clients.

        Handles:
        1. Update Message.image_requested flag if images referenced
        2. Broadcast chat.message_created events for real-time delivery

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.
        """
        from chatlab.models import Message
        from core.outbox.helpers import broadcast_domain_objects

        messages = results.get("messages", [])

        # Update image_requested flag if needed
        if self.image_requested and messages:
            logger.info("Image requested for simulation %s - flag set on Message records", context.simulation_id)
            for msg in messages:
                if isinstance(msg, Message):
                    msg.image_requested = True
                    await msg.asave(update_fields=["image_requested"])

        # Broadcast messages
        if messages:
            await broadcast_domain_objects(
                event_type="chat.message_created",
                objects=messages,
                context=context,
                payload_builder=lambda msg: {
                    "message_id": msg.id,
                    "content": msg.content or "",
                    "role": msg.role,
                    "is_from_ai": msg.is_from_ai,
                    "display_name": msg.display_name or "",
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                    "image_requested": msg.image_requested,
                },
            )


class PatientResultsOutputSchema(BaseModel):
    """Final results payload — scored observations and assessments.

    Does NOT inherit PatientResponseBaseMixin (no user-facing messages).

    **Persistence** (declarative):
    - metadata → simulation.SimulationMetadata polymorphic models via auto-mapper
    - llm_conditions_check → NOT PERSISTED

    **Metadata Structure**:
    Same polymorphic structure as PatientInitialOutputSchema:
    - ``kind="lab_result"`` → simulation.LabResult
    - ``kind="rad_result"`` → simulation.RadResult
    - ``kind="patient_history"`` → simulation.PatientHistory
    - ``kind="patient_demographics"`` → simulation.PatientDemographics
    - ``kind="generic"`` → simulation.SimulationMetadata (fallback)

    **WebSocket Broadcasting**:
    - Broadcasts ``metadata.created`` events for results/assessments
    - Enables real-time UI updates when scores/observations are ready
    """

    model_config = ConfigDict(extra="forbid")

    metadata: list[MetadataItem] = Field(
        ...,
        description="Scored observations and final assessment (polymorphic structure with 'kind' discriminator)"
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Completion and workflow flags"
    )

    __persist__ = {"metadata": None}  # None = auto-map via item.__orm_model__
    __persist_primary__ = "metadata"

    async def post_persist(self, results, context):
        """Broadcast metadata creation to WebSocket clients.

        Creates outbox events for metadata objects (labs, radiology results,
        scored observations, assessments) to enable real-time UI updates.

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.
        """
        from core.outbox.helpers import broadcast_domain_objects

        metadata = results.get("metadata", [])
        if metadata:
            await broadcast_domain_objects(
                event_type="metadata.created",
                objects=metadata,
                context=context,
                payload_builder=lambda meta: {
                    "metadata_id": meta.id,
                    "kind": meta.polymorphic_ctype.model if hasattr(meta, 'polymorphic_ctype') else "generic",
                    "key": meta.key,
                    "value": meta.value,
                },
            )
