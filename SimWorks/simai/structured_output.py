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
        text_format=PatientResponse,
    )
    parsed = response.output_parsed

Author: Jackfruit SimWorks
"""

from typing import List
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class MedicalHistoryItem(BaseModel):
    diagnosis: str
    is_resolved: bool
    duration: str


class AdditionalMetadataItem(BaseModel):
    key: str
    value: str


class PatientDemographics(BaseModel):
    name: str
    age: int
    gender: Literal["male", "female"]
    location: str
    medical_history: List[MedicalHistoryItem]
    additional: Optional[List[AdditionalMetadataItem]] = []


class SimulationMetadataItem(BaseModel):
    key: str
    value: str


class ScenarioMetadata(BaseModel):
    diagnosis: str
    chief_complaint: str


class Metadata(BaseModel):
    patient_metadata: PatientDemographics
    simulation_metadata: Optional[List[SimulationMetadataItem]] = []
    scenario_metadata: ScenarioMetadata


class MessageItem(BaseModel):
    sender: Literal["patient"]
    content: str


class InitialPatientResponse(BaseModel):
    image_requested: bool
    messages: List[MessageItem]
    metadata: Metadata


class PatientResponse(BaseModel):
    image_requested: bool
    messages: List[MessageItem]


class LabResult(BaseModel):
    order_name: str = Field(
        ..., description="The name of the order using standardized terminology."
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
        None, description="The result comment, if applicable, or null."
    )

    class Config:
        extra = "forbid"


class RadResult(BaseModel):
    order_name: str = Field(
        ..., description="The name of the order using standardized terminology."
    )
    result_value: str = Field(..., description="The result of the order.")
    result_flag: Literal["UNK", "NORMAL", "ABNORMAL", "CRITICAL"] = Field(
        ..., description="The result flag."
    )

    class Config:
        extra = "forbid"


class PatientResults(BaseModel):
    lab_results: Optional[List[LabResult]] = Field(
        None,
        description="The lab results of the patient. Each item is a lab result object.",
    )
    radiology_results: Optional[List[RadResult]] = Field(
        None,
        description="The radiology results of the patient. Each item is a radiology result object.",
    )

    class Config:
        extra = "forbid"
