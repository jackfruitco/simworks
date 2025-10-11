# simcore/ai/schemas/types.py
from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, Dict, Optional, List, Literal, Annotated, Union, TypeAlias

from pydantic import Field

from .base import StrictBaseModel, Boolish

logger = logging.getLogger(__name__)


# ---------- Attachments (DTO) -------------------------------------------------------
class AttachmentItem(StrictBaseModel):
    kind: Literal["image"]
    b64: Optional[str] = None
    file: Optional[Any] = None
    url: Optional[str] = None

    format: Optional[str] = None  # "png", "jpeg"
    size: Optional[str] = None  # "1024x1024"
    background: Optional[str] = None

    provider_meta: Dict[str, Any] = Field(default_factory=dict)

    # linkage after persistence
    db_pk: Optional[int] = None
    db_model: Optional[str] = None
    slug: Optional[str] = None


# ---------- Messages (DTO) ---------------------------------------------------------
class MessageItem(StrictBaseModel):
    role: str
    content: str

    db_pk: Optional[int] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    attachments: List[AttachmentItem] = Field(default_factory=list)


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
    value: str = Field(...) #, max_length=1250)


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


# ---------- Tools (DTO) ------------------------------------------------------------
class ToolItem(StrictBaseModel):
    kind: str  # e.g., "image_generation"
    function: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ---------- Request/Response (DTO) -------------------------------------------------
class LLMRequest(StrictBaseModel):
    """Normalized request sent to a provider (DTO used internally)."""
    model: Optional[str] = None
    messages: List[MessageItem]
    schema_cls: Any = None
    tools: Optional[List[ToolItem]] = None
    tool_choice: Optional[str] = None
    temperature: Optional[float] = 0.2
    max_output_tokens: Optional[int] = None
    stream: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    previous_response_id: Optional[str] = None
    image_format: Optional[str] = None


class LLMResponse(StrictBaseModel):
    """Normalized provider response (DTO used internally)."""
    messages: List[MessageItem]
    metadata: List[MetafieldItem]
    usage: Dict[str, int] = Field(default_factory=dict)

    image_requested: Optional[bool] = None

    provider_meta: Dict[str, Any] = Field(default_factory=dict)
    db_pk: Optional[int] = None

    @classmethod
    def normalize(cls, resp: Any, _from: str, *, schema_cls=None) -> "LLMResponse":
        logger.debug(f"{cls.__name__} received request to normalize response from {_from}. Forwarding...")
        mod = import_module(f"simcore.ai.providers.{_from}")
        data = mod.normalize_response(resp, schema_cls=schema_cls)
        return data if isinstance(data, cls) else cls(**data)


class StreamChunk(StrictBaseModel):
    delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    usage_partial: Optional[Dict[str, int]] = None
