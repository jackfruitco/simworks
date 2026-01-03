"""Reusable output item types for simulation schemas.

This module contains base output items that can be used across multiple schemas.
"""

from pydantic import Field

from orchestrai_django.components.schemas import DjangoBaseOutputItem, DjangoBaseOutputBlock


class LLMConditionsCheckItem(DjangoBaseOutputItem):
    """Generic LLM workflow condition check.

    Used for internal flags that control workflow logic but are not persisted
    to the database. Examples: 'ready_for_questions', 'session_complete', etc.
    """
    key: str = Field(..., description="Condition key/name")
    value: str = Field(..., description="Condition value (often 'true'/'false')")


class HotwashInitialBlock(DjangoBaseOutputBlock):
    """
    Initial hotwash (post-session) feedback block.

    **Design**: Simplified structure with direct field definitions rather than
    wrapper item classes. All fields are required.

    **Usage**: Embedded in HotwashInitialSchema as the `metadata` field.
    Contains structured feedback data that gets persisted to SimulationFeedback.

    **Fields**:
    - `correct_diagnosis`: bool - Learner diagnostic accuracy
    - `correct_treatment_plan`: bool - Treatment plan appropriateness
    - `patient_experience`: int (0-5) - Patient experience rating (5=excellent)
    - `overall_feedback`: str (min 1 char) - Narrative feedback

    **Note**: Uses `DjangoBaseOutputBlock` (no identity required at block level).
    """

    correct_diagnosis: bool = Field(
        ...,
        description="Whether the learner reached the correct diagnosis"
    )

    correct_treatment_plan: bool = Field(
        ...,
        description="Whether the learner developed an appropriate treatment plan"
    )

    patient_experience: int = Field(
        ...,
        ge=0,
        le=5,
        description="Patient experience rating (0=poor, 5=excellent)"
    )

    overall_feedback: str = Field(
        ...,
        min_length=1,
        description="Overall narrative feedback for the learner"
    )
