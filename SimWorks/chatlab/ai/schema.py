# chatlab/ai/schema.py
from typing import List, Annotated
from typing import Literal
from typing import Optional

from pydantic import Field

from simcore.ai.schemas import StrictBaseModel, StrictOutputSchema, NormalizedAIMessage, NormalizedAIMetadata


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
    role: Literal["patient"]
    content: str


class LLMConditionsCheckItem(StrictBaseModel):
    key: str
    value: str


class PatientInitialOutputSchema(StrictOutputSchema):
    image_requested: bool
    # messages: List[MessageItem]
    # metadata: Metadata
    messages: list[NormalizedAIMessage] = Field(default_factory=list)
    metadata: list[NormalizedAIMetadata] = Field(default_factory=list)
    llm_conditions_check: List[LLMConditionsCheckItem]


class PatientReplyOutputSchema(StrictOutputSchema):
    image_requested: bool
    messages: List[MessageItem]
    metadata: Metadata
    llm_conditions_check: List[LLMConditionsCheckItem]


class LabResult(StrictBaseModel):
    result_name: str = Field(
        ..., description="The name of the specific lab test using standardized terminology. For example, 'Hematocrit' or 'LDL-Cholesterol'.'"
    )
    panel_name: str = Field(
        ..., description="The name of the lab panel that the test result is included in using standardized terminology. For example, 'Complete Blood Count' or 'Lipid Panel'."
    )
    result_value: float = Field(
        ..., description="The result value of the specific lab test, without the unit."
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
    result_name: str = Field(
        ..., description="The name of the order using standardized terminology."
    )
    result_value: str = Field(..., description="The result of the order.")
    result_flag: Literal["UNK", "NORMAL", "ABNORMAL", "CRITICAL"] = Field(
        ..., description="The result flag."
    )


class ResultsMetadata(StrictBaseModel):
    lab_results: List[LabResult] = Field(
        ...,
        description="The lab results of the patient. Each item is a lab result object.",
    )
    radiology_results: List[RadResult] = Field(
        ...,
        description="The radiology results of the patient. Each item is a radiology result object.",
    )

class PatientResultsOutputSchema(StrictOutputSchema):
    metadata: ResultsMetadata
    llm_conditions_check: List[LLMConditionsCheckItem]

    # lab_results: List[LabResult] = Field(
    #     ...,
    #     description="The lab results of the patient. Each item is a lab result object.",
    # )
    # radiology_results: List[RadResult] = Field(
    #     ...,
    #     description="The radiology results of the patient. Each item is a radiology result object.",
    # )

Boolish = Literal["true", "false", "partial"]

class SimulationFeedbackOutputSchema(StrictOutputSchema):
    correct_diagnosis: Boolish = Field(
        ..., description="Whether the user provided the correct diagnosis."
    )
    correct_treatment_plan: Boolish = Field(
        ..., description="Whether the user provided the correct treatment plan."
    )
    patient_experience: Annotated[int, Field(ge=0, le=5)] = Field(
        ..., description="The patient's experience with the encounter rated 0-5.."
    )
    overall_feedback: str = Field(
        ..., description="The feedback text from the simulation."
    )
