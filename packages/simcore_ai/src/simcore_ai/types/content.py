# simcore_ai/types/content.py
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


InputContent = TextContent | ImageContent | AudioContent | FileContent | ScreenshotContent
OutputContent = TextContent | ToolContent | ToolResultContent | ImageContent | AudioContent
