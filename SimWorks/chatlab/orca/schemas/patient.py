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
    """

    metadata: list[MetadataItem] = Field(
        ...,
        description="Patient demographics and initial metadata (polymorphic structure with 'kind' discriminator)"
    )

    __persist__ = {"metadata": None}  # None = auto-map via item.__orm_model__
    __persist_primary__ = "messages"


class PatientReplyOutputSchema(PatientResponseBaseMixin):
    """Output for subsequent patient reply turns.

    **Persistence** (declarative):
    - messages → chatlab.Message via ``persist_messages`` (inherited from mixin)
    - image_requested → Persisted to Message.image_requested field via context
    - llm_conditions_check → NOT PERSISTED
    """

    image_requested: bool = Field(
        ...,
        description="Whether the response references images/scans"
    )

    __persist_primary__ = "messages"

    async def post_persist(self, results, context):
        """Update Message records with image_requested flag."""
        if self.image_requested:
            logger.info("Image requested for simulation %s - flag set on Message records", context.simulation_id)
            # Update all messages created in this persist cycle
            from chatlab.models import Message
            messages = results.get("messages", [])
            if messages:
                for msg in messages:
                    if isinstance(msg, Message):
                        msg.image_requested = True
                        await msg.asave(update_fields=["image_requested"])


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
