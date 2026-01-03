# orchestrai/types/content.py
"""
Defines various types of content and their roles used within the application. It
includes structured representations of text, image, audio, file, screenshot, tool
event, and result content. Additionally, it encompasses enumerations for
identifying content roles.

Classes in this module extend the `StrictBaseModel` for validation purposes and
use type hinting for stricter schema enforcement.
"""
from enum import Enum
from typing import Literal, Any

from pydantic import Field

from .base import StrictBaseModel

__all__ = (
    "ContentRole",
    "BaseTextContent",
    "BaseImageContent",
    "BaseAudioContent",
    "BaseFileContent",
    "BaseScreenshotContent",
    "BaseToolCallContent",
    "BaseToolResultContent",
    "BaseJsonContent",
)

class ContentRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    DEVELOPER = "developer"
    ASSISTANT = "assistant"
    PATIENT = "patient"
    INSTRUCTOR = "instructor"
    FACILITATOR = "facilitator"
    TOOL = "tool"


class BaseTextContent(StrictBaseModel):
    """Base shape for text content (backend-agnostic)."""
    text: str


class BaseImageContent(StrictBaseModel):
    """Base shape for image content (base64-encoded)."""
    mime_type: str
    data_b64: str


class BaseAudioContent(StrictBaseModel):
    """Base shape for audio content (base64-encoded)."""
    mime_type: str
    data_b64: str


class BaseFileContent(StrictBaseModel):
    """Base shape for generic file content (base64-encoded)."""
    mime_type: str
    data_b64: str


class BaseScreenshotContent(StrictBaseModel):
    """Base shape for screenshots (base64-encoded)."""
    mime_type: str
    data_b64: str


class BaseToolCallContent(StrictBaseModel):
    """Base shape for tool call content."""
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": False}
    )


class BaseToolResultContent(StrictBaseModel):
    """Base shape for tool result content."""
    call_id: str
    # The result can be text, JSON, or binary (e.g., base64 image bytes)
    result_text: str | None = None
    result_json: dict[str, Any] | None = None
    mime_type: str | None = None
    data_b64: str | None = None


class BaseJsonContent(StrictBaseModel):
    """Base structured JSON content."""
    value: dict[str, Any]
