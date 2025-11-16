from typing import Optional, Literal, Dict, Any, Annotated, TypeAlias, Union

from pydantic import Field

from simcore_ai_django.types import StrictBaseModel, Boolish


# ---------- Metadata (DTO) ---------------------------------------------------------
class BaseMetafield(StrictBaseModel):
    kind: str
    key: str = Field(..., max_length=255)
    db_pk: Optional[int] = None


class GenericMetafield(BaseMetafield):
    kind: Literal["generic"]
    value: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class LabResultMetafield(BaseMetafield):
    kind: Literal["lab_result"]
    panel_name: Optional[str] = Field(..., max_length=100)
    result_name: str = Field(..., )
    result_value: str = Field(..., )
    result_unit: Optional[str] = Field(..., max_length=20)
    reference_range_low: Optional[str] = Field(..., max_length=50)
    reference_range_high: Optional[str] = Field(..., max_length=50)
    result_flag: Literal["normal", "abnormal"] = Field(..., max_length=20)
    result_comment: Optional[str] = Field(..., max_length=500)


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


class FeedbackMetafieldBase(BaseMetafield):
    kind: Literal["simulation_feedback"]


class CorrectDiagnosisFeedback(FeedbackMetafieldBase):
    kind: Literal["correct_diagnosis"]
    key: Literal["correct_diagnosis"]
    value: Boolish = Field(..., max_length=5)


class CorrectTreatmentPlanFeedback(FeedbackMetafieldBase):
    kind: Literal["correct_treatment_plan"]
    key: Literal["correct_treatment_plan"]
    value: Boolish = Field(..., max_length=5)


class PatientExperienceFeedback(FeedbackMetafieldBase):
    kind: Literal["patient_experience"]
    key: Literal["patient_experience"]
    value: Annotated[int, Field(ge=0, le=5)] = Field(...)


class OverallFeedbackMetafield(FeedbackMetafieldBase):
    kind: Literal["overall_feedback"]
    key: Literal["overall_feedback"]
    value: str = Field(...)  # , max_length=1250)


MetafieldItem: TypeAlias = Annotated[
    Union[
        GenericMetafield,
        LabResultMetafield,
        RadResultMetafield,
        PatientHistoryMetafield,
        PatientDemographicsMetafield,
        SimulationMetafield,
        ScenarioMetafield,
        CorrectDiagnosisFeedback,
        CorrectTreatmentPlanFeedback,
        PatientExperienceFeedback,
        OverallFeedbackMetafield,
    ],
    Field(discriminator="kind"),
]