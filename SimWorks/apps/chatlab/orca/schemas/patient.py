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

    **Durable Events**:
    - ChatLab emits outbox-backed events after generic domain persistence completes
    - ``simulation.metadata.results_created`` is the canonical metadata refresh event
    - ``metadata.created`` remains a temporary compatibility alias
    """

    metadata: list[MetadataItem] = Field(
        ...,
        description="Patient demographics and initial metadata (polymorphic structure with 'kind' discriminator)",
    )

    __persist__: ClassVar[dict[str, None]] = {"metadata": None}  # auto-map via item.__orm_model__
    __persist_primary__ = "messages"

    async def post_persist(self, results, context):
        """Reserved hook for persistence-only follow-ups."""
        return None


class PatientReplyOutputSchema(PatientResponseBaseMixin):
    """Output for subsequent patient reply turns.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - metadata → simcore.SimulationMetadata polymorphic models via key-based upsert
    - image_request.requested → sets Message.image_requested flag and enqueues image task
    - llm_conditions_check → NOT PERSISTED

    **Durable Events**:
    - ChatLab emits outbox-backed events after generic domain persistence completes
    - ``simulation.metadata.results_created`` is the canonical metadata refresh event
    - ``metadata.created`` remains a temporary compatibility alias
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

    image_request: ImageRequest | None = Field(
        default=None,
        description="Structured image generation intent (set requested=true when the patient references an image or scan)",
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
        if (
            self.image_request
            and self.image_request.requested
            and not self.image_request.prompt.strip()
        ):
            raise ValueError(
                "image_request.prompt is required when image_request.requested is true"
            )
        return self

    @property
    def should_generate_image(self) -> bool:
        return self.image_request is not None and bool(self.image_request.requested)

    async def post_persist(self, results, context):
        """Update Message records and run persistence-local follow-ups.

        Handles:
        1. Update Message.image_requested flag if images referenced
        2. Enqueue image generation follow-up when requested

        Args:
            results: Dict of persisted objects from __persist__ declarations
            context: PersistContext with simulation_id, correlation_id, etc.
        """
        from apps.chatlab.models import Message

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

        return None


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

    **Durable Events**:
    - ChatLab emits outbox-backed events after generic domain persistence completes
    - ``simulation.metadata.results_created`` is the canonical metadata refresh event
    - ``metadata.created`` remains a temporary compatibility alias
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
        """Reserved hook for persistence-only follow-ups."""
        return None
