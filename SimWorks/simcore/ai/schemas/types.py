# simcore/ai/schemas/types.py
from __future__ import annotations

from typing import Any, Dict, Optional, List, Literal, Annotated, Union

from pydantic import Field

from .base import StrictBaseModel


# ---------- Attachments (DTO) -------------------------------------------------------
class AttachmentItem(StrictBaseModel):
    kind: Literal["image"]
    b64: Optional[str] = None
    file: Optional[Any] = None
    url: Optional[str] = None

    format: Optional[str] = None   # "png", "jpeg"
    size: Optional[str] = None     # "1024x1024"
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
    key: str
    db_pk: Optional[int] = None


class GenericMetafield(BaseMetafield):
    kind: Literal["generic"]
    value: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class LabResultMetafield(BaseMetafield):
    kind: Literal["lab_result"]
    panel_name: Optional[str] = None
    result_name: str
    result_value: str
    result_unit: str
    reference_range_low: str
    reference_range_high: str
    result_flag: str
    result_comment: str


class RadResultMetafield(BaseMetafield):
    kind: Literal["rad_result"]
    value: str
    flag: str


class PatientHistoryMetafield(BaseMetafield):
    kind: Literal["patient_history"]
    value: str
    is_resolved: bool
    duration: str


class SimulationFeedbackMetafield(BaseMetafield):
    kind: Literal["simulation_feedback"]
    value: str


class PatientDemographicsMetafield(BaseMetafield):
    kind: Literal["patient_demographics"]
    value: str


class SimulationMetafield(BaseMetafield):
    kind: Literal["simulation_metadata"]
    value: str


class ScenarioMetafield(BaseMetafield):
    kind: Literal["scenario"]
    value: str


MetafieldItem = Annotated[
    Union[
        GenericMetafield,
        LabResultMetafield,
        RadResultMetafield,
        PatientHistoryMetafield,
        SimulationFeedbackMetafield,
        PatientDemographicsMetafield,
        SimulationMetafield,
        ScenarioMetafield,
    ],
    Field(discriminator="kind"),
]


# ---------- Tools (DTO) ------------------------------------------------------------
class ToolItem(StrictBaseModel):
    kind: str                  # e.g., "image_generation"
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


class StreamChunk(StrictBaseModel):
    delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    usage_partial: Optional[Dict[str, int]] = None