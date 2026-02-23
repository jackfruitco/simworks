"""Reusable output item types for simulation schemas.

This module contains base output items that can be used across multiple schemas.
These are plain Pydantic models for use with Pydantic AI.
"""

from pydantic import BaseModel, Field, ConfigDict


class LLMConditionsCheckItem(BaseModel):
    """Generic LLM workflow condition check.

    Used for internal flags that control workflow logic but are not persisted
    to the database. Examples: 'ready_for_questions', 'session_complete', etc.
    """
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., description="Condition key/name")
    value: str = Field(..., description="Condition value (often 'true'/'false')")


class InitialFeedbackBlock(BaseModel):
    """
    Initial (post-session) feedback block.

    **Usage**: Embedded in GenerateInitialSimulationFeedback as the `metadata` field.
    Contains structured feedback data that gets persisted to SimulationFeedback.

    **Fields**:
    - `correct_diagnosis`: bool - Learner diagnostic accuracy
    - `correct_treatment_plan`: bool - Treatment plan appropriateness
    - `patient_experience`: int (0-5) - Patient experience rating (5=excellent)
    - `overall_feedback`: str (min 1 char) - Narrative feedback
    """
    model_config = ConfigDict(extra="forbid")

    correct_diagnosis: bool = Field(
        ...,
        description="Whether the user identified the correct diagnosis during the simulation."
    )

    correct_treatment_plan: bool = Field(
        ...,
        description="Whether the user proposed an appropriate treatment plan"
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
