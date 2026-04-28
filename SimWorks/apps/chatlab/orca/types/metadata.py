from typing import Annotated, Any, Literal

from pydantic import Field

from orchestrai_django.types import StrictBaseModel


class BaseMetafield(StrictBaseModel):
    kind: str
    key: str = Field(..., max_length=255)
    db_pk: int | None = None


class GenericMetafield(BaseMetafield):
    kind: Literal["generic"]
    value: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LabResultMetafield(BaseMetafield):
    kind: Literal["lab_result"]
    panel_name: str | None = Field(..., max_length=100)
    result_name: str = Field(
        ...,
    )
    result_value: str = Field(
        ...,
    )
    result_unit: str | None = Field(..., max_length=20)
    reference_range_low: str | None = Field(..., max_length=50)
    reference_range_high: str | None = Field(..., max_length=50)
    result_flag: Literal["normal", "abnormal"] = Field(..., max_length=20)
    result_comment: str | None = Field(..., max_length=500)


class RadResultMetafield(BaseMetafield):
    kind: Literal["rad_result"]
    value: str
    flag: str


class PatientHistoryMetafield(BaseMetafield):
    kind: Literal["patient_history"]
    value: str
    is_resolved: bool
    duration: str


class PatientDemographicsMetafield(BaseMetafield):
    kind: Literal["patient_demographics"]
    value: str


class SimulationMetafield(BaseMetafield):
    kind: Literal["simulation_metadata"]
    value: str


class ScenarioMetafield(BaseMetafield):
    kind: Literal["scenario"]
    value: str


type MetafieldItem = Annotated[
    GenericMetafield
    | LabResultMetafield
    | RadResultMetafield
    | PatientHistoryMetafield
    | PatientDemographicsMetafield
    | SimulationMetafield
    | ScenarioMetafield,
    Field(discriminator="kind"),
]
