# chatlab/orca/schemas/patient.py
"""
Patient output schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

from pydantic import BaseModel, Field, ConfigDict

from orchestrai.types import ResultMessageItem, ResultMetafield
from simulation.orca.schemas.output_items import LLMConditionsCheckItem
from .mixins import PatientResponseBaseMixin


class PatientInitialOutputSchema(PatientResponseBaseMixin):
    """
    Output for the initial patient response turn.

    **Usage**: First turn of simulated patient interaction, establishing patient
    identity, demographics, and initial presentation.

    **Schema Structure**:
    - `messages` (from PatientResponseBaseMixin): list[DjangoOutputItem], min 1 item
        → Initial patient greeting/introduction message
    - `metadata`: list[DjangoOutputItem]
        → Patient demographics, vitals, medical history
    - `llm_conditions_check` (from PatientResponseBaseMixin): list[LLMConditionsCheckItem]
        → Internal workflow flags (e.g., "ready_for_questions")

    **OpenAI Compatibility**: ✓ Validated at decoration time
    - Root type: object
    - No unions at root level
    - Strict mode compatible

    **Persistence**: Handled by `PatientInitialPersistence`
    - messages → chatlab.Message (content field)
    - metadata → simulation.SimulationMetadata (polymorphic routing)
    - llm_conditions_check → NOT PERSISTED (ephemeral workflow flags)

    **Identity**: schemas.chatlab.standardized_patient.PatientInitialOutputSchema
    """
    metadata: list[ResultMetafield] = Field(
        ...,
        description="Patient demographics and initial metadata"
    )


class PatientReplyOutputSchema(PatientResponseBaseMixin):
    """
    Output for subsequent patient reply turns.

    **Usage**: Follow-up patient responses during conversation, answering learner
    questions or providing additional information.

    **Schema Structure**:
    - `image_requested`: bool
        → Flag indicating if response references visual content (X-ray, CT scan, etc.)
        → May trigger image generation workflow
    - `messages` (from PatientResponseBaseMixin): list[DjangoOutputItem], min 1 item
        → Patient's reply to learner's question
    - `llm_conditions_check` (from PatientResponseBaseMixin): list[LLMConditionsCheckItem]
        → Internal workflow flags (e.g., "continue_conversation", "session_complete")

    **OpenAI Compatibility**: ✓ Validated at decoration time
    - Root type: object
    - No unions at root level
    - Strict mode compatible

    **Persistence**: Handled by `PatientReplyPersistence`
    - image_requested → Logged (may trigger side effects)
    - messages → chatlab.Message (content field)
    - llm_conditions_check → NOT PERSISTED

    **Identity**: schemas.chatlab.standardized_patient.PatientReplyOutputSchema
    """
    image_requested: bool = Field(
        ...,
        description="Whether the response references images/scans"
    )


class PatientResultsOutputSchema(BaseModel):
    """Plain Pydantic model for Pydantic AI result_type."""
    model_config = ConfigDict(extra="forbid")
    """
    Final "results" payload for the interaction.

    **Usage**: End-of-session structured output containing scored observations,
    assessments, and completion metadata. No user-facing messages.

    **Schema Structure**:
    - `metadata`: list[DjangoOutputItem]
        → Scored observations (e.g., "communication_score": "4/5")
        → Final diagnosis assessment (e.g., "diagnosis_accuracy": "correct")
        → Treatment plan evaluation
    - `llm_conditions_check`: list[LLMConditionsCheckItem], optional
        → Completion flags (e.g., "session_complete": "true")

    **Note**: Does NOT inherit PatientResponseBaseMixin because there are no
    user-facing messages in the results output - only structured metadata.

    **OpenAI Compatibility**: ✓ Validated at decoration time
    - Root type: object
    - No unions at root level
    - Strict mode compatible

    **Persistence**: Handled by `PatientResultsPersistence`
    - metadata → simulation.SimulationMetadata (assessment records)
    - llm_conditions_check → NOT PERSISTED

    **Identity**: schemas.chatlab.standardized_patient.PatientResultsOutputSchema
    """
    metadata: list[ResultMessageItem] = Field(
        ...,
        description="Scored observations and final assessment"
    )
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Completion and workflow flags"
    )
