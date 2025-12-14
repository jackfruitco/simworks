from typing import Literal

from pydantic import Field

from orchestrai_django.components.schemas import DjangoBaseOutputItem, DjangoBaseOutputBlock

class LLMConditionsCheckItem(DjangoBaseOutputItem):
    """LLM conditions check item."""
    key: str
    value: str

class CorrectDiagnosisItem(DjangoBaseOutputItem):
    """Correct diagnosis item."""
    key: Literal["correct_diagnosis"] = Field(...)
    value: bool


class CorrectTreatmentPlanItem(DjangoBaseOutputItem):
    """Correct treatment plan item."""
    key: Literal["correct_treatment_plan"] = Field(...)
    value: bool


class PatientExperienceItem(DjangoBaseOutputItem):
    """Patient experience item."""
    key: Literal["patient_experience"] = Field(...)
    value: int = Field(..., ge=0, le=5)


class OverallFeedbackItem(DjangoBaseOutputItem):
    """Overall feedback item."""
    key: Literal["overall_feedback"] = Field(...)
    value: str


class HotwashInitialBlock(DjangoBaseOutputBlock):
    """Initial hotwash feedback block.

    Uses `DjangoBaseOutputBlock` (no identity required on block level).
    """
    correct_diagnosis: CorrectDiagnosisItem
    correct_treatment_plan: CorrectTreatmentPlanItem
    patient_experience: PatientExperienceItem
    overall_feedback: OverallFeedbackItem