"""Polymorphic metadata item types for structured LLM outputs.

These Pydantic models extend ResultMetafield to match the polymorphic
Django ORM models (LabResult, RadResult, PatientHistory, etc.).

Each item class includes:
- ``__orm_model__``: Django model path for auto-mapper routing
- ``kind``: Discriminator field for union type (enables OpenAI Structured Outputs)
- All required fields matching the Django model structure

Usage in schemas:
    metadata: list[MetadataItem] = Field(...)

The persistence engine uses ``__orm_model__`` to route each item to its
specific Django model (e.g., LabResultItem → simulation.LabResult).
"""

from typing import Annotated, Literal

from pydantic import Field

from orchestrai.types import ResultMetafield


class LabResultItem(ResultMetafield):
    """Lab result metadata item → simulation.LabResult.

    Maps LLM-generated lab results to the LabResult polymorphic model.

    **Fields**:
    - key: Result name (maps to LabResult.key)
    - value: Result value (maps to LabResult.value)
    - kind: Discriminator (must be "lab_result")
    - panel_name: Optional panel grouping (e.g., "Complete Blood Count")
    - result_unit: Unit of measurement (e.g., "mg/dL", "mmol/L")
    - reference_range_low: Lower bound of normal range
    - reference_range_high: Upper bound of normal range
    - result_flag: "normal" or "abnormal"
    - result_comment: Optional clinical interpretation
    """

    kind: Literal["lab_result"] = Field(
        ..., description="Discriminator field (must be 'lab_result')"
    )
    panel_name: str | None = Field(
        None, max_length=100, description="Lab panel name (e.g., 'Complete Blood Count')"
    )
    result_unit: str | None = Field(
        None, max_length=20, description="Unit of measurement (e.g., 'mg/dL')"
    )
    reference_range_low: str | None = Field(
        None, max_length=50, description="Lower bound of reference range"
    )
    reference_range_high: str | None = Field(
        None, max_length=50, description="Upper bound of reference range"
    )
    result_flag: Literal["normal", "abnormal"] = Field(
        ..., description="Result flag indicating normal or abnormal"
    )
    result_comment: str | None = Field(
        None, max_length=500, description="Optional clinical comment or interpretation"
    )

    __orm_model__ = "simcore.LabResult"


class RadResultItem(ResultMetafield):
    """Radiology result metadata item → simulation.RadResult.

    Maps LLM-generated radiology results to the RadResult polymorphic model.

    **Fields**:
    - key: Result name (e.g., "Chest X-Ray")
    - value: Result description/findings
    - kind: Discriminator (must be "rad_result")
    - result_flag: Clinical flag (e.g., "normal", "abnormal", "critical")
    """

    kind: Literal["rad_result"] = Field(
        ..., description="Discriminator field (must be 'rad_result')"
    )
    result_flag: str = Field(
        ..., max_length=10, description="Result flag (e.g., 'normal', 'abnormal')"
    )

    __orm_model__ = "simcore.RadResult"


class PatientHistoryItem(ResultMetafield):
    """Patient history metadata item → simulation.PatientHistory.

    Maps LLM-generated patient history to the PatientHistory polymorphic model.

    **Fields**:
    - key: Diagnosis name (maps to PatientHistory.key and .diagnosis property)
    - value: History description
    - kind: Discriminator (must be "patient_history")
    - is_resolved: Whether the condition is currently resolved
    - duration: Duration string (e.g., "2 years", "since childhood")
    """

    kind: Literal["patient_history"] = Field(
        ..., description="Discriminator field (must be 'patient_history')"
    )
    is_resolved: bool = Field(..., description="Whether the condition is currently resolved")
    duration: str = Field(
        ...,
        max_length=100,
        description="Duration of the condition (e.g., '2 years', 'since childhood')",
    )

    __orm_model__ = "simcore.PatientHistory"


class PatientDemographicsItem(ResultMetafield):
    """Patient demographics metadata item → simulation.PatientDemographics.

    Maps LLM-generated patient demographics to the PatientDemographics polymorphic model.
    Simple key/value pairs for demographic information (age, gender, etc.).

    **Fields**:
    - key: Demographic field name (e.g., "age", "gender", "ethnicity")
    - value: Demographic value
    - kind: Discriminator (must be "patient_demographics")
    """

    kind: Literal["patient_demographics"] = Field(
        ..., description="Discriminator field (must be 'patient_demographics')"
    )

    __orm_model__ = "simcore.PatientDemographics"


class SimulationMetadataItem(ResultMetafield):
    """Generic simulation metadata item → simcore.SimulationMetadata.

    Fallback for generic key/value metadata that doesn't fit specific categories.
    Maps to the base SimulationMetadata model (non-polymorphic subclass).

    **Fields**:
    - key: Metadata key
    - value: Metadata value
    - kind: Discriminator (must be "generic")
    """

    kind: Literal["generic"] = Field(..., description="Discriminator field (must be 'generic')")

    __orm_model__ = "simcore.SimulationMetadata"


# Union type for all metadata items with discriminator-based routing
MetadataItem = Annotated[
    LabResultItem
    | RadResultItem
    | PatientHistoryItem
    | PatientDemographicsItem
    | SimulationMetadataItem,
    Field(discriminator="kind"),
]
