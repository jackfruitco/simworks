# simcore/ai/schemas/output_schema.py
from __future__ import annotations

from typing import List

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
    image_requested: bool = False
    messages: list[OutputMessageItem] = Field(default_factory=list)
    metadata: list[OutputMetafieldItem] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)


class PatientReplyOutputSchema(StrictOutputSchema):
    image_requested: bool = False
    messages: list[OutputMessageItem] = Field(default_factory=list)
    metadata: list[OutputMetafieldItem] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)


class PatientResultsOutputSchema(StrictOutputSchema):
    metadata: list[OutputMetafieldItem] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)


class SimulationFeedbackOutputSchema(StrictOutputSchema):
    correct_diagnosis: Boolish
    correct_treatment_plan: Boolish
    patient_experience: int = Field(ge=0, le=5)
    overall_feedback: str