# simulation/orca/schemas/feedback.py
"""
Feedback schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

from pydantic import BaseModel, Field, ConfigDict

from .output_items import HotwashInitialBlock, LLMConditionsCheckItem


class HotwashInitialSchema(BaseModel):
    """
    Initial patient feedback (hotwash) schema.

    **Usage**: Post-session feedback provided to the learner after simulation
    completion. Includes scored assessments and narrative feedback.

    **Schema Structure**:
    - `metadata`: HotwashInitialBlock (required)
        -> `correct_diagnosis`: bool - Whether learner reached correct diagnosis
        -> `correct_treatment_plan`: bool - Whether treatment plan was appropriate
        -> `patient_experience`: int (0-5) - Patient experience rating
        -> `overall_feedback`: str (min 1 char) - Narrative feedback for learner
    - `llm_conditions_check`: list[LLMConditionsCheckItem]
        -> Internal workflow flags (e.g., "feedback_complete")

    **Persistence**: Handled by `HotwashInitialPersistence`
    - metadata.correct_diagnosis -> simulation.SimulationFeedback (key="hotwash_correct_diagnosis")
    - metadata.correct_treatment_plan -> simulation.SimulationFeedback (key="hotwash_correct_treatment_plan")
    - metadata.patient_experience -> simulation.SimulationFeedback (key="hotwash_patient_experience")
    - metadata.overall_feedback -> simulation.SimulationFeedback (key="hotwash_overall_feedback")
    - llm_conditions_check -> NOT PERSISTED
    """
    model_config = ConfigDict(extra="forbid")

    llm_conditions_check: list[LLMConditionsCheckItem] = Field(
        ...,
        description="Internal workflow conditions"
    )
    metadata: HotwashInitialBlock = Field(
        ...,
        description="Feedback data block"
    )
