# orchestrai/types/build_content.py
"""
Build-side content types for ergonomic construction.

These types are used for:
- Constructing outbound request payloads
- Building messages in application code
- Adapting provider responses

Key characteristics:
- May have defaults on fields for ergonomic construction
- Subclass Base* types to ensure structural isomorphism
- Can be converted to Result* types for schema validation

DO NOT use these in schema definitions - use Result* types instead.
"""

from typing import Literal

from pydantic import Field

from .content import (
    BaseAudioContent,
    BaseFileContent,
    BaseImageContent,
    BaseJsonContent,
    BaseScreenshotContent,
    BaseTextContent,
    BaseToolCallContent,
    BaseToolResultContent,
)

__all__ = (
    "BuildAudioContent",
    "BuildContent",
    "BuildFileContent",
    "BuildImageContent",
    "BuildJsonContent",
    "BuildScreenshotContent",
    "BuildTextContent",
    "BuildToolCallContent",
    "BuildToolResultContent",
)


# ---- Build-side content types (ergonomic, with defaults) ----


class BuildTextContent(BaseTextContent):
    """Text content for construction - ergonomic defaults provided."""

    type: Literal["text"] = "text"  # Default value provided


class BuildImageContent(BaseImageContent):
    """Image content for construction - ergonomic defaults provided."""

    type: Literal["image"] = "image"


class BuildAudioContent(BaseAudioContent):
    """Audio content for construction - ergonomic defaults provided."""

    type: Literal["audio"] = "audio"


class BuildFileContent(BaseFileContent):
    """File content for construction - ergonomic defaults provided."""

    type: Literal["file"] = "file"


class BuildScreenshotContent(BaseScreenshotContent):
    """Screenshot content for construction - ergonomic defaults provided."""

    type: Literal["screenshot"] = "screenshot"


class BuildToolCallContent(BaseToolCallContent):
    """Tool call content for construction - ergonomic defaults provided."""

    type: Literal["tool_call"] = "tool_call"
    arguments_json: str = "{}"  # Default empty object


class BuildToolResultContent(BaseToolResultContent):
    """Tool result content for construction - ergonomic defaults provided."""

    type: Literal["tool_result"] = "tool_result"
    result_text: str | None = None  # Default None
    result_json_str: str | None = Field(
        default=None, description="Tool result as JSON-encoded string (for arbitrary structures)"
    )
    mime_type: str | None = None
    data_b64: str | None = None


class BuildJsonContent(BaseJsonContent):
    """JSON content for construction - ergonomic defaults provided."""

    type: Literal["json"] = "json"


# ---- Union type for build content ----

BuildContent = (
    BuildTextContent
    | BuildImageContent
    | BuildAudioContent
    | BuildFileContent
    | BuildScreenshotContent
    | BuildToolCallContent
    | BuildToolResultContent
    | BuildJsonContent
)
