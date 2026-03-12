# chatlab/orca/schemas/patient.py
"""
Patient output schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

import logging
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.simcore.orca.schemas.metadata_items import MetadataItem
from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem

from .mixins import PatientResponseBaseMixin

logger = logging.getLogger(__name__)


def _metadata_kind(meta) -> str:
    """Resolve metadata kind without touching lazy ORM relations in async context."""
    model_name = getattr(getattr(meta, "_meta", None), "model_name", "") or ""
    kind_by_model = {
        "labresult": "lab_result",
        "radresult": "rad_result",
        "patienthistory": "patient_history",
        "patientdemographics": "patient_demographics",
        "simulationfeedback": "simulation_feedback",
        "simulationmetadata": "generic",
    }
    if model_name in kind_by_model:
        return kind_by_model[model_name]

    class_name = meta.__class__.__name__.lower()
    return kind_by_model.get(class_name, "generic")


class PatientInitialOutputSchema(PatientResponseBaseMixin):
    """Output for the initial patient response turn.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - metadata → simcore.SimulationMetadata polymorphic models via auto-mapper
    - llm_conditions_check → NOT PERSISTED

    **Metadata Structure**:
    The LLM must generate metadata items with the correct polymorphic structure:
    - ``kind="lab_result"`` → simcore.LabResult
    - ``kind="rad_result"`` → simcore.RadResult
    - ``kind="patient_history"`` → simcore.PatientHistory
    - ``kind="patient_demographics"`` → simcore.PatientDemographics
    - ``kind="generic"`` → simcore.SimulationMetadata (fallback)

    Each item type includes required fields matching the Django model structure.

    **WebSocket Broadcasting**:
    - Broadcasts ``chat.message_created`` events for patient messages
    - Broadcasts ``metadata.created`` events for demographics/history/results
    - Enables real-time UI updates when initial response is generated
    """

    metadata: list[MetadataItem] = Field(
        ...,
        description="Patient demographics and initial metadata (polymorphic structure with 'kind' discriminator)",
    )

    __persist__: ClassVar[dict[str, None]] = {"metadata": None}  # auto-map via item.__orm_model__
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
        from apps.chatlab.media_payloads import build_message_media_payload
        from apps.common.outbox.helpers import broadcast_domain_objects

        # Broadcast messages
        messages = results.get("messages", [])
        if messages:
            await broadcast_domain_objects(
                event_type="chat.message_created",
                objects=messages,
                context=context,
                payload_builder=lambda msg: {
                    "message_id": msg.id,
                    "id": msg.id,
                    "content": msg.content or "",
                    "role": msg.role,
                    "is_from_ai": msg.is_from_ai,
                    "isFromAi": msg.is_from_ai,
                    "isFromAI": msg.is_from_ai,
                    "display_name": msg.display_name or "",
                    "displayName": msg.display_name or "",
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                    "conversation_id": msg.conversation_id,
                    "conversation_type": "simulated_patient",
                    "messageType": msg.message_type,
                    "sender_id": msg.sender_id,
                    "senderId": msg.sender_id,
                    "status": "completed",
                    "source_message_id": msg.source_message_id,
                    **build_message_media_payload(msg),
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
                    "kind": _metadata_kind(meta),
                    "key": meta.key,
                    "value": meta.value,
                },
            )


class PatientReplyOutputSchema(PatientResponseBaseMixin):
    """Output for subsequent patient reply turns.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - metadata → simcore.SimulationMetadata polymorphic models via key-based upsert
    - image_requested → Persisted to Message.image_requested field via context
    - llm_conditions_check → NOT PERSISTED

    **WebSocket Broadcasting**:
    - Broadcasts ``chat.message_created`` events for patient reply messages
    - Broadcasts ``metadata.created`` events for metadata updates
    - Enables real-time UI updates when patient responds
    """

    class ImageRequest(BaseModel):
        """Structured image-generation intent emitted by the patient reply model."""

        model_config = ConfigDict(extra="forbid")

        requested: bool = Field(..., description="Whether an image should be generated")
        prompt: str = Field(
            default="",
            description="Clinically grounded prompt for image generation",
        )
        caption: str | None = Field(
            default=None,
            description="Optional user-facing caption shown with the image",
        )
        clinical_focus: str | None = Field(
            default=None,
            description="Short descriptor of the clinical finding to emphasize",
        )

    image_requested: bool = Field(..., description="Legacy image request flag")
    image_request: ImageRequest | None = Field(
        default=None,
        description="Structured image generation intent (preferred over image_requested)",
    )
    metadata: list[MetadataItem] = Field(
        ...,
        description="Incremental metadata updates emitted during follow-up turns",
    )

    from apps.chatlab.orca.persisters import persist_metadata_upsert as _persist_metadata_upsert

    __persist__: ClassVar[dict[str, None]] = {"metadata": _persist_metadata_upsert}
    __persist_primary__ = "messages"

    @model_validator(mode="after")
    def _validate_image_request_prompt(self):
        if self.image_request and self.image_request.requested and not self.image_request.prompt.strip():
            raise ValueError("image_request.prompt is required when image_request.requested is true")
        return self

    @property
    def should_generate_image(self) -> bool:
        if self.image_request is not None:
            return bool(self.image_request.requested)
        return bool(self.image_requested)

    async def post_persist(self, results, context):
        """Update Message records and broadcast to WebSocket clients.

        Handles:
        1. Update Message.image_requested flag if images referenced
        2. Broadcast chat.message_created events for real-time delivery
        3. Broadcast metadata.created events for metadata upserts

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.
        """
        from apps.chatlab.media_payloads import build_message_media_payload
        from apps.chatlab.models import Message
        from apps.common.outbox.helpers import broadcast_domain_objects

        messages = results.get("messages", [])

        # Update image_requested flag if needed
        if self.should_generate_image and messages:
            logger.info(
                "Image requested for simulation %s - flag set on Message records",
                context.simulation_id,
            )
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
                    "id": msg.id,
                    "content": msg.content or "",
                    "role": msg.role,
                    "is_from_ai": msg.is_from_ai,
                    "isFromAi": msg.is_from_ai,
                    "isFromAI": msg.is_from_ai,
                    "display_name": msg.display_name or "",
                    "displayName": msg.display_name or "",
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                    "image_requested": msg.image_requested,
                    "conversation_id": msg.conversation_id,
                    "conversation_type": "simulated_patient",
                    "messageType": msg.message_type,
                    "sender_id": msg.sender_id,
                    "senderId": msg.sender_id,
                    "status": "completed",
                    "source_message_id": msg.source_message_id,
                    **build_message_media_payload(msg),
                },
            )

        if self.should_generate_image and messages:
            source_msg = next(
                (msg for msg in messages if getattr(msg, "is_from_ai", False)),
                messages[0],
            )
            prompt = ""
            caption = None
            clinical_focus = None
            if self.image_request is not None:
                prompt = self.image_request.prompt.strip()
                caption = self.image_request.caption
                clinical_focus = self.image_request.clinical_focus

            # Backward compatibility: if only legacy bool is present, derive prompt from reply text.
            if not prompt:
                prompt = source_msg.content or "Generate a clinically realistic image."

            try:
                from apps.chatlab.tasks import enqueue_generate_patient_image_task

                enqueue_generate_patient_image_task(
                    simulation_id=context.simulation_id,
                    conversation_id=source_msg.conversation_id,
                    source_message_id=source_msg.id,
                    prompt=prompt,
                    caption=caption,
                    clinical_focus=clinical_focus,
                    correlation_id=context.correlation_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue image generation for source message %s: %s",
                    getattr(source_msg, "id", None),
                    exc,
                )

        metadata = results.get("metadata", [])
        if metadata:
            await broadcast_domain_objects(
                event_type="metadata.created",
                objects=metadata,
                context=context,
                payload_builder=lambda meta: {
                    "metadata_id": meta.id,
                    "kind": _metadata_kind(meta),
                    "key": meta.key,
                    "value": meta.value,
                },
            )


class PatientResultsOutputSchema(BaseModel):
    """Final results payload — scored observations and assessments.

    Does NOT inherit PatientResponseBaseMixin (no user-facing messages).

    **Persistence** (declarative):
    - metadata → simcore.SimulationMetadata polymorphic models via auto-mapper
    - llm_conditions_check → NOT PERSISTED

    **Metadata Structure**:
    Same polymorphic structure as PatientInitialOutputSchema:
    - ``kind="lab_result"`` → simulation.LabResult
    - ``kind="rad_result"`` → simulation.RadResult
    - ``kind="patient_history"`` → simulation.PatientHistory
    - ``kind="patient_demographics"`` → simulation.PatientDemographics
    - ``kind="generic"`` → simcore.SimulationMetadata (fallback)

    **WebSocket Broadcasting**:
    - Broadcasts ``metadata.created`` events for results/assessments
    - Enables real-time UI updates when scores/observations are ready
    """

    model_config = ConfigDict(extra="forbid")

    metadata: list[MetadataItem] = Field(
        ...,
        description="Scored observations and final assessment (polymorphic structure with 'kind' discriminator)",
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ..., description="Completion and workflow flags"
    )

    __persist__: ClassVar[dict[str, None]] = {"metadata": None}  # auto-map via item.__orm_model__
    __persist_primary__ = "metadata"

    async def post_persist(self, results, context):
        """Broadcast metadata creation to WebSocket clients.

        Creates outbox events for metadata objects (labs, radiology results,
        scored observations, assessments) to enable real-time UI updates.

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.
        """
        from apps.common.outbox.helpers import broadcast_domain_objects

        metadata = results.get("metadata", [])
        if metadata:
            await broadcast_domain_objects(
                event_type="metadata.created",
                objects=metadata,
                context=context,
                payload_builder=lambda meta: {
                    "metadata_id": meta.id,
                    "kind": _metadata_kind(meta),
                    "key": meta.key,
                    "value": meta.value,
                },
            )
