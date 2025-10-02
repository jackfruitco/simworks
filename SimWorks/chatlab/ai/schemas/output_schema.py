# simcore/ai/schemas/output_schema.py
from __future__ import annotations

from pydantic import Field

from simcore.ai.schemas import (
    StrictOutputSchema,
    Boolish,
    OutputMessageItem,
    OutputMetafieldItem,
)


class LLMConditionsCheckItem(StrictOutputSchema):
    key: str
    value: str


class PatientInitialOutputSchema(StrictOutputSchema):
    image_requested: bool
    messages: list[OutputMessageItem] = Field(...)
    metadata: list[OutputMetafieldItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


class PatientReplyOutputSchema(StrictOutputSchema):
    image_requested: bool = Field(...)
    messages: list[OutputMessageItem] = Field(...)
    # metadata: list[OutputMetafieldItem] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


class PatientResultsOutputSchema(StrictOutputSchema):
    metadata: list[OutputMetafieldItem] = Field(...)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(...)


class SimulationFeedbackOutputSchema(StrictOutputSchema):
    correct_diagnosis: Boolish = Field(...)
    correct_treatment_plan: Boolish = Field(...)
    patient_experience: int = Field(..., ge=0, le=5)
    overall_feedback: str = Field(...)
