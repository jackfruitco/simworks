# simcore/ai/schemas/feedback.py


from pydantic import Field

from orchestrai_django.components.schemas import DjangoBaseOutputSchema
from orchestrai_django.decorators import schema
from .output_items import HotwashInitialBlock, LLMConditionsCheckItem


@schema
class HotwashInitialSchema(DjangoBaseOutputSchema):
    """
    Initial patient feedback (hotwash) schema.

    **Usage**: Post-session feedback provided to the learner after simulation
    completion. Includes scored assessments and narrative feedback.

    **Schema Structure**:
    - `metadata`: HotwashInitialBlock (required)
        → `correct_diagnosis`: bool - Whether learner reached correct diagnosis
        → `correct_treatment_plan`: bool - Whether treatment plan was appropriate
        → `patient_experience`: int (0-5) - Patient experience rating
        → `overall_feedback`: str (min 1 char) - Narrative feedback for learner
    - `llm_conditions_check`: list[LLMConditionsCheckItem]
        → Internal workflow flags (e.g., "feedback_complete")

    **OpenAI Compatibility**: ✓ Validated at decoration time
    - Root type: object
    - No unions at root level
    - Strict mode compatible
    - All fields have direct types (bool/int/str), no wrapper classes

    **Persistence**: Handled by `HotwashInitialPersistence`
    - metadata.correct_diagnosis → simulation.SimulationFeedback (key="hotwash_correct_diagnosis")
    - metadata.correct_treatment_plan → simulation.SimulationFeedback (key="hotwash_correct_treatment_plan")
    - metadata.patient_experience → simulation.SimulationFeedback (key="hotwash_patient_experience")
    - metadata.overall_feedback → simulation.SimulationFeedback (key="hotwash_overall_feedback")
    - llm_conditions_check → NOT PERSISTED

    **Identity**: schemas.simcore.feedback.HotwashInitialSchema
    """
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(..., json_schema_extra={"kind": "conditions_check"})
    metadata: HotwashInitialBlock = Field(..., json_schema_extra={"kind": "feedback"})
