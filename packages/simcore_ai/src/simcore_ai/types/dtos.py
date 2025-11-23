# simcore_ai/types/dtos.py
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .tools import BaseLLMTool, LLMToolChoice, LLMToolCall, LLMToolCallDelta

logger = logging.getLogger(__name__)
from .base import StrictBaseModel

ResponseSchemaType: TypeAlias = type[BaseModel]  # TODO: ResponseSchemaType Protocol


# ---------- Content Parts (DTO) -------------------------------------------------------
class ContentRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    DEVELOPER = "developer"
    ASSISTANT = "assistant"
    PATIENT = "patient"
    INSTRUCTOR = "instructor"
    FACILITATOR = "facilitator"
    TOOL = "tool"


class TextContent(StrictBaseModel):
    type: Literal["input_text"] = "input_text"
    text: str


class ImageContent(StrictBaseModel):
    type: Literal["input_image"] = "input_image"
    mime_type: str
    data_b64: str


class AudioContent(StrictBaseModel):
    type: Literal["input_audio"] = "input_audio"
    mime_type: str
    data_b64: str


class FileContent(StrictBaseModel):
    type: Literal["input_file"] = "input_file"
    mime_type: str
    data_b64: str


class ScreenshotContent(StrictBaseModel):
    type: Literal["computer_screenshot"] = "computer_screenshot"
    mime_type: str
    data_b64: str


class ToolContent(StrictBaseModel):
    type: Literal["tool_call"] = "tool_call"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultContent(StrictBaseModel):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    # The result can be text, JSON, or binary (e.g., base64 image bytes)
    result_text: str | None = None
    result_json: dict[str, Any] | None = None
    mime_type: str | None = None
    data_b64: str | None = None


# ContentPart: TypeAlias = (
#         TextContent |
#         ImageContent |
#         AudioContent |
#         FileContent |
#         ScreenshotContent |
#         ToolContent |
#         ToolResultContent
# )

InputContent = TextContent | ImageContent | AudioContent | FileContent | ScreenshotContent
OutputContent = TextContent | ToolContent | ToolResultContent | ImageContent | AudioContent


# ---------- LLM Types (DTO) -------------------------------------------------------
class InputItem(StrictBaseModel):
    """Single input message with a role and one or more content parts."""
    role: ContentRole
    content: list[InputContent]


class OutputItem(StrictBaseModel):
    """Single output message with a role and one or more content parts."""
    role: ContentRole
    content: list[OutputContent]
    item_meta: dict[str, Any] = Field(default_factory=dict)


class UsageContent(StrictBaseModel):
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
    input: list[InputItem]

    # Identity
    namespace: str | None = None
    kind: str | None = None
    name: str | None = None

    # Correlation
    correlation_id: UUID = Field(default_factory=uuid4)

    # Response format (provider-agnostic)
    response_schema: ResponseSchemaType | None = None  # Pydantic model
    response_schema_json: dict | None = None  # JSON schema from model
    provider_response_format: dict | None = None  # Provider-specific response format

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

    # Request
    request_correlation_id: UUID | None = None
    request: Request | None = None

    # Provider/client + timing
    provider_name: str | None = None
    client_name: str | None = None
    received_at: datetime | None = None

    output: list[OutputItem] = Field(default_factory=list)
    usage: UsageContent | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    provider_meta: dict[str, Any] = Field(default_factory=dict)


class StreamChunk(StrictBaseModel):
    correlation_id: UUID = Field(default_factory=uuid4)
    lab_key: str
    simulation_id: int

    is_final: bool = False
    delta: str = ""
    tool_call_delta: LLMToolCallDelta | None = None
    usage_partial: Optional[Dict[str, int]] = None
