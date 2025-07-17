"""
structured_output.py

This module defines Pydantic models used to parse and validate structured responses
from OpenAI's Responses API. These models correspond to patient-facing simulation outputs
such as chat messages, patient metadata, simulation metadata, and scenario context.

Usage:
    - Used with `client.responses.parse(...)` to enforce schema correctness.
    - Enables typed access to parsed AI-generated patient response content.

Note:
    This is distinct from Django models and GraphQL schema definitions.
    It is purpose-built for parsing structured JSON returned from AI response formatting.

Example:
    response = client.responses.parse(
        model="gpt-4o",
        input=[...],
        text_format=PatientReplySchema,
    )
    parsed = response.output_parsed

Author: Jackfruit SimWorks
"""

from typing import List
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from pydantic import Extra
from pydantic import Field


class StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"


class StrictSchema(StrictBaseModel):
    pass


class ABCMetadataItem(StrictBaseModel):
    key: str = Field(..., description="The key of the metadata item.")
    value: str = Field(..., description="The value of the metadata item.")
    # attribute: Literal[
    #     "PatientDemographics",
    #     "PatientHistory",
    #     "SimulationMetadata",
    #     "ScenarioMetadata"
    # ] = Field(..., description="The attribute of the metadata item.")


class PatientHistoryMetafield(ABCMetadataItem):
    key: str = Field(..., description="The diagnosis for this history item.")
    value: None = Field(..., description="This field is not used.")
    # attribute: Literal["PatientHistory"]

    is_resolved: bool
    duration: str


class PatientDemographicsMetafield(ABCMetadataItem):
    pass
    # attribute: Literal["PatientDemographics"]


# class PatientDemographics(StrictBaseModel):
#     name: str
#     age: int
#     gender: Literal["male", "female"]
#     location: str
#     medical_history: List[MedicalHistoryItem]
#     additional: Optional[List[AdditionalMetadataItem]] = []


class SimulationDataMetafield(ABCMetadataItem):
    pass
    # attribute: Literal["SimulationMetadata"]


class ScenarioMetadata(StrictBaseModel):
    diagnosis: str = Field(
        ..., description="The diagnosis of the patient."
    )
    chief_complaint: str = Field(
        ..., description="The chief complaint of the patient."
    )
    # treatment: str = Field(..., description="The treatment of the patient.")
    # outcome: str = Field(..., description="The outcome of the patient.")
    # treatment_plan: str = Field(..., description="The treatment plan of the patient.")
    # treatment_plan_summary: str = Field(
    #     ..., description="The treatment plan summary of the patient."
    # )


class Metadata(StrictBaseModel):
    patient_demographics: List[PatientDemographicsMetafield]
    patient_history: List[PatientHistoryMetafield]
    simulation_metadata: List[SimulationDataMetafield]
    scenario_data: ScenarioMetadata


class MessageItem(StrictBaseModel):
    sender: Literal["patient"]
    content: str


class PatientInitialSchema(StrictSchema):
    image_requested: bool
    messages: List[MessageItem]
    metadata: Metadata


class PatientReplySchema(StrictSchema):
    image_requested: bool
    messages: List[MessageItem]
    metadata: Metadata


class LabResult(StrictBaseModel):
    order_name: str = Field(
        ..., description="The name of the order using standardized terminology."
    )
    panel_name: str = Field(
        ..., description="The name of the lab panel  that the test is included in using standardized terminology."
    )
    result_value: float = Field(
        ..., description="The result value of the test, without the unit."
    )
    result_unit: str = Field(..., description="The unit of the result value.")
    reference_range_low: float = Field(
        ..., description="The lower limit of the reference range, without the unit."
    )
    reference_range_high: float = Field(
        ..., description="The upper limit of the reference range, without the unit."
    )
    result_flag: Literal[
        "HIGH", "LOW", "POS", "NEG", "UNK", "NORMAL", "ABNORMAL", "CRITICAL"
    ] = Field(..., description="The result flag.")
    result_comment: Optional[str] = Field(
        ..., description="The result comment, if applicable, or null."
    )


class RadResult(StrictBaseModel):
    order_name: str = Field(
        ..., description="The name of the order using standardized terminology."
    )
    result_value: str = Field(..., description="The result of the order.")
    result_flag: Literal["UNK", "NORMAL", "ABNORMAL", "CRITICAL"] = Field(
        ..., description="The result flag."
    )


class PatientResultsSchema(StrictSchema):
    lab_results: List[LabResult] = Field(
        ...,
        description="The lab results of the patient. Each item is a lab result object.",
    )
    radiology_results: List[RadResult] = Field(
        ...,
        description="The radiology results of the patient. Each item is a radiology result object.",
    )
