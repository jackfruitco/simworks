# simcore/ai/providers/openai/schema_overrides.py
from __future__ import annotations

from pydantic import Field

from ...schemas import StrictBaseModel
from ...schemas.output_types import OutputGenericMetafield, OutputPatientHistoryMetafield, \
    OutputPatientDemographicsMetafield, OutputSimulationMetafield, OutputScenarioMetafield, OutputLabResultMetafield, \
    OutputRadResultMetafield


class OutputMetafieldItemOverride(StrictBaseModel):
    generic_metadata: list[OutputGenericMetafield] = Field(...)
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
