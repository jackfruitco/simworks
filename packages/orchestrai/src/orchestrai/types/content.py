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

from pydantic import Field

from .base import StrictBaseModel

__all__ = (
    "BaseAudioContent",
    "BaseFileContent",
    "BaseImageContent",
    "BaseJsonContent",
    "BaseScreenshotContent",
    "BaseTextContent",
    "BaseToolCallContent",
    "BaseToolResultContent",
    "ContentRole",
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
    """Base shape for tool call content.

    OpenAI strict mode compliance: arguments stored as JSON-encoded string
    instead of dict[str, Any] to avoid open object schema violations.
    """

    call_id: str
    name: str
    arguments_json: str = Field(
        ..., description="Tool arguments as JSON-encoded string (for OpenAI strict mode compliance)"
    )


class BaseToolResultContent(StrictBaseModel):
    """Base shape for tool result content."""

    call_id: str
    # The result can be text, JSON, or binary (e.g., base64 image bytes)
    result_text: str | None = Field(...)
    # OpenAI strict mode requires all objects to be closed (additionalProperties: false).
    # For arbitrary JSON results, use result_json_str (JSON-encoded string) instead of dict.
    # Deprecated: result_json: dict[str, Any] (violates OpenAI strict mode)
    result_json_str: str | None = Field(
        ..., description="Tool result as JSON-encoded string (for arbitrary structures)"
    )
    mime_type: str | None = Field(...)
    data_b64: str | None = Field(...)


class BaseJsonContent(StrictBaseModel):
    """
    Base structured JSON content.

    OpenAI strict mode requires all objects to be closed (additionalProperties: false).
    For arbitrary JSON values, use value_json (JSON-encoded string) instead of dict.
    """

    value_json: str = Field(
        ..., description="JSON content as encoded string (for arbitrary structures)"
    )
