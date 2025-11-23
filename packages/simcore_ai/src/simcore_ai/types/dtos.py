# simcore_ai/types/dtos.py


import logging
import warnings
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import Field

from .tools import BaseLLMTool, LLMToolChoice, LLMToolCall, LLMToolCallDelta

logger = logging.getLogger(__name__)
from .base import StrictBaseModel


# ---------- Content Parts (DTO) -------------------------------------------------------
class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    DEVELOPER = "developer"
    ASSISTANT = "assistant"
    PATIENT = "patient"
    INSTRUCTOR = "instructor"
    FACILITATOR = "facilitator"
    TOOL = "tool"


class LLMTextPart(StrictBaseModel):
    type: Literal["input_text"] = "input_text"
    text: str


class LLMImagePart(StrictBaseModel):
    type: Literal["input_image"] = "input_image"
    mime_type: str
    data_b64: str


class LLMAudioPart(StrictBaseModel):
    type: Literal["input_audio"] = "input_audio"
    mime_type: str
    data_b64: str


class LLMFilePart(StrictBaseModel):
    type: Literal["input_file"] = "input_file"
    mime_type: str
    data_b64: str


class LLMScreenshotPart(StrictBaseModel):
    type: Literal["computer_screenshot"] = "computer_screenshot"
    mime_type: str
    data_b64: str


class LLMToolCallPart(StrictBaseModel):
    type: Literal["tool_call"] = "tool_call"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMToolResultPart(StrictBaseModel):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    # The result can be text, JSON, or binary (e.g., base64 image bytes)
    result_text: str | None = None
    result_json: dict[str, Any] | None = None
    mime_type: str | None = None
    data_b64: str | None = None


LLMContentPart: TypeAlias = (
        LLMTextPart |
        LLMImagePart |
        LLMAudioPart |
        LLMFilePart |
        LLMScreenshotPart |
        LLMToolCallPart |
        LLMToolResultPart
)


# ---------- LLM Types (DTO) -------------------------------------------------------
# Input (request)
class LLMRequestMessage(StrictBaseModel):
    role: LLMRole
    content: list[LLMTextPart | LLMImagePart | LLMAudioPart]  # no tool parts


# Output (response)
class LLMResponseItem(StrictBaseModel):
    role: LLMRole
    content: list[
        LLMTextPart | LLMToolCallPart | LLMToolResultPart | LLMImagePart | LLMAudioPart
        ]
    item_meta: dict[str, Any] = Field(default_factory=dict)


class LLMUsage(StrictBaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_tokens: int = 0
    total_tokens: int = 0

    # allow unknown fields from provider
    model_config = {
        **StrictBaseModel.model_config,
        "extra": "allow",
    }


class ToolItem(StrictBaseModel):
    kind: str  # e.g., "image_generation"
    function: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ---------- Request/Response (DTO) -------------------------------------------------
class Request(StrictBaseModel):
    model: str | None = None
    messages: list[LLMRequestMessage]

    # Identity
    namespace: str | None = None
    kind: str | None = None
    name: str | None = None

    # Correlation
    correlation_id: UUID = Field(default_factory=uuid4)

    @property
    def codec(self) -> None:
        warnings.warn("Deprecated. Use `BaseService().codec` instead instead")
        return None

    # Response format (provider-agnostic)
    output_schema_cls: Any = None  # renamed from output_schema_cls
    output_schema: dict | None = None

    # Tooling
    tools: list[BaseLLMTool] = Field(default_factory=list)
    tool_choice: LLMToolChoice = "auto"

    # Misc
    previous_response_id: str | None = None
    temperature: float | None = 0.2
    max_output_tokens: int | None = None
    stream: bool = False
    image_format: str | None = None


class Response(StrictBaseModel):
    # Identity echoed back (operation identity)
    namespace: str | None = None
    kind: str | None = None
    name: str | None = None

    # Correlation
    correlation_id: UUID = Field(default_factory=uuid4)
    request_correlation_id: UUID | None = None

    # Provider/client + timing
    provider_name: str | None = None
    client_name: str | None = None
    received_at: datetime | None = None

    output: list[LLMResponseItem] = Field(default_factory=list)
    usage: LLMUsage | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    provider_meta: dict[str, Any] = Field(default_factory=dict)


class LLMStreamChunk(StrictBaseModel):
    correlation_id: UUID = Field(default_factory=uuid4)
    lab_key: str
    simulation_id: int

    is_final: bool = False
    delta: str = ""
    tool_call_delta: LLMToolCallDelta | None = None
    usage_partial: Optional[Dict[str, int]] = None
