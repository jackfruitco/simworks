"""
response_schema.py

This module defines Pydantic models used to parse and validate structured responses
from OpenAI's Responses API. These models correspond to patient-facing simulation outputs
such as chat messages, patient metadata, simulation metadata, and scenario context.

All main response schemas are decorated with @schema to enable:
  - Import-time validation against OpenAI Responses API requirements
  - Schema caching for performance (~100% reduction in schema generation overhead)
  - Provider compatibility tagging

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
from typing import List, Annotated, Literal, Optional

from pydantic import Field

# Import OrchestrAI schema infrastructure
try:
    from orchestrai.components.schemas import BaseOutputSchema
    from orchestrai.decorators import schema
    ORCHESTRAI_AVAILABLE = True
except ImportError:
    # Fallback if orchestrai not available (shouldn't happen in production)
    from pydantic import BaseModel as BaseOutputSchema
    ORCHESTRAI_AVAILABLE = False
    def schema(cls):
        """Fallback no-op decorator if orchestrai not available."""
        return cls


class StrictBaseModel(BaseOutputSchema):
    """Base model with strict validation (extra fields forbidden).

    Inherits from BaseOutputSchema to enable OrchestrAI schema framework:
    - Import-time validation
    - Schema caching
    - Provider compatibility tracking
    """
    class Config:
        extra = "forbid"


class StrictSchema(StrictBaseModel):
    """Alias for StrictBaseModel for backward compatibility."""
    pass


# Component schemas (not decorated - used as building blocks)

class ABCMetadataItem(StrictBaseModel):
    """Base class for metadata items."""
    key: str = Field(..., description="The key of the metadata item.")
    value: str = Field(..., description="The value of the metadata item.")


class PatientHistoryMetafield(ABCMetadataItem):
    """Patient medical history metadata item."""
    key: str = Field(..., description="The diagnosis for this history item.")
    value: None = Field(..., description="This field is not used.")
    is_resolved: bool
    duration: str


class PatientDemographicsMetafield(ABCMetadataItem):
    """Patient demographics metadata item."""
    pass


class SimulationDataMetafield(ABCMetadataItem):
    """Simulation-specific metadata item."""
    pass


class ScenarioMetadata(StrictBaseModel):
    """Scenario context metadata."""
    diagnosis: str = Field(
        ..., description="The diagnosis of the patient."
    )
    chief_complaint: str = Field(
        ..., description="The chief complaint of the patient."
    )


class Metadata(StrictBaseModel):
    """Container for all metadata types."""
    patient_demographics: List[PatientDemographicsMetafield]
    patient_history: List[PatientHistoryMetafield]
    simulation_metadata: List[SimulationDataMetafield]
    scenario_data: ScenarioMetadata


class MessageItem(StrictBaseModel):
    """A single message in the conversation."""
    sender: Literal["patient"]
    content: str


class LabResult(StrictBaseModel):
    """Laboratory test result."""
    result_name: str = Field(
        ...,
        description="The name of the specific lab test using standardized terminology. "
                    "For example, 'Hematocrit' or 'LDL-Cholesterol'."
    )
    panel_name: str = Field(
        ...,
        description="The name of the lab panel that the test result is included in using "
                    "standardized terminology. For example, 'Complete Blood Count' or 'Lipid Panel'."
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
    """Radiology result."""
    result_name: str = Field(
        ..., description="The name of the order using standardized terminology."
    )
    result_value: str = Field(..., description="The result of the order.")
    result_flag: Literal["UNK", "NORMAL", "ABNORMAL", "CRITICAL"] = Field(
        ..., description="The result flag."
    )


# Type alias for feedback boolean-ish values
Boolish = Literal["true", "false", "partial"]


# Main response schemas (decorated for OrchestrAI integration)

@schema
class PatientInitialSchema(StrictSchema):
    """Schema for initial patient introduction response.

    Used when starting a new simulation to generate the patient's
    first message and initial metadata.
    """
    image_requested: bool
    messages: List[MessageItem]
    metadata: Metadata


@schema
class PatientReplySchema(StrictSchema):
    """Schema for patient reply during conversation.

    Used for ongoing conversation turns where the patient responds
    to the user's questions or statements.
    """
    image_requested: bool
    messages: List[MessageItem]
    metadata: Metadata


@schema
class PatientResultsSchema(StrictSchema):
    """Schema for patient clinical results (lab/radiology).

    Used when generating lab or radiology results based on
    user-requested orders.
    """
    lab_results: List[LabResult] = Field(
        ...,
        description="The lab results of the patient. Each item is a lab result object.",
    )
    radiology_results: List[RadResult] = Field(
        ...,
        description="The radiology results of the patient. Each item is a radiology result object.",
    )


@schema
class SimulationFeedbackSchema(StrictSchema):
    """Schema for end-of-simulation feedback.

    Used when the simulation completes to provide assessment
    of the user's performance.
    """
    correct_diagnosis: Boolish = Field(
        ..., description="Whether the user provided the correct diagnosis."
    )
    correct_treatment_plan: Boolish = Field(
        ..., description="Whether the user provided the correct treatment plan."
    )
    patient_experience: Annotated[int, Field(ge=0, le=5)] = Field(
        ..., description="The patient's experience with the encounter rated 0-5."
    )
    overall_feedback: str = Field(
        ..., description="The feedback text from the simulation."
    )
