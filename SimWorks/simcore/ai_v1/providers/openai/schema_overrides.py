# simcore/ai_v1/providers/openai/schema_overrides.py
from __future__ import annotations

from pydantic import Field

from ...schemas import StrictBaseModel
from ...schemas.output_types import (
    OutputGenericMetafield,
    OutputPatientHistoryMetafield,
    OutputPatientDemographicsMetafield,
    OutputSimulationMetafield,
    OutputScenarioMetafield,
    # Patient Result types
    OutputLabResultMetafield,
    OutputRadResultMetafield,
    # Feedback types
    OutputCorrectDiagnosisFeedback,
    OutputCorrectTreatmentPlanFeedback,
    OutputPatientExperienceFeedback,
    OutputOverallFeedback
)


class OutputMetafieldItemOverride(StrictBaseModel):
    patient_history: list[OutputPatientHistoryMetafield] = Field(...)
    patient_demographics: list[OutputPatientDemographicsMetafield] = Field(...)
    simulation_metadata: list[OutputSimulationMetafield] = Field(...)
    scenario_data: list[OutputScenarioMetafield] = Field(...)

    def flatten(self) -> list[dict]:
        flat: list[dict] = []

        for items in self.model_dump().values():
            flat.extend(items)
        return flat


class OutputResultItemOverride(StrictBaseModel):
    lab_results: list[OutputLabResultMetafield] = Field(...)
    rad_results: list[OutputRadResultMetafield] = Field(...)

    def flatten(self) -> list[dict]:
        flat: list[dict] = []

        for items in self.model_dump().values():
            flat.extend(items)
        return flat


class OutputFeedbackEndexItemOverride(StrictBaseModel):
    correct_treatment_plan: list[OutputCorrectTreatmentPlanFeedback] = Field(
        ..., min_length=1, max_length=1)
    correct_diagnosis: list[OutputCorrectDiagnosisFeedback] = Field(
        ..., min_length=1, max_length=1)
    patient_experience: list[OutputPatientExperienceFeedback] = Field(
        ..., min_length=1, max_length=1)
    overall_feedback: list[OutputOverallFeedback] = Field(
        ..., min_length=1, max_length=1)

    def flatten(self) -> list[dict]:
        flat: list[dict] = []

        for items in self.model_dump().values():
            flat.extend(items)
        return flat