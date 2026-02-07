# orchestrai/types/result_content.py
"""
Result-side content types for strict schema generation and validation.

These types are used for:
- OpenAI Structured Outputs schema definitions
- Response validation/parsing
- Persistence routing

Key characteristics:
- Subclass StrictBaseModel (extra="forbid")
- NO defaults on fields (all required unless explicitly Optional)
- Generate strict JSON Schema with additionalProperties: false
- Literal discriminators without defaults

DO NOT use these for construction - use Build* types instead.
"""

from typing import Literal, Any

from pydantic import Field

from .base import StrictBaseModel

__all__ = (
    "ResultContent",
    "ResultTextContent",
    "ResultImageContent",
    "ResultAudioContent",
    "ResultFileContent",
    "ResultScreenshotContent",
    "ResultToolCallContent",
    "ResultToolResultContent",
    "ResultJsonContent",
)


# ---- Result-side content types (strict, schema-authoritative) ----

class ResultTextContent(StrictBaseModel):
    """Text content for structured outputs - strict, no defaults."""
    type: Literal["text"]
    text: str = Field(..., min_length=1)


class ResultImageContent(StrictBaseModel):
    """Image content for structured outputs - strict, no defaults."""
    type: Literal["image"]
    mime_type: str
    data_b64: str


class ResultAudioContent(StrictBaseModel):
    """Audio content for structured outputs - strict, no defaults."""
    type: Literal["audio"]
    mime_type: str
    data_b64: str


class ResultFileContent(StrictBaseModel):
    """File content for structured outputs - strict, no defaults."""
    type: Literal["file"]
    mime_type: str
    data_b64: str


class ResultScreenshotContent(StrictBaseModel):
    """Screenshot content for structured outputs - strict, no defaults."""
    type: Literal["screenshot"]
    mime_type: str
    data_b64: str


class ResultToolCallContent(StrictBaseModel):
    """Tool call content for structured outputs - strict, no defaults.

    Note: arguments_json is a JSON-encoded string to comply with OpenAI strict mode
    (dict[str, Any] violates additionalProperties: false requirement).
    """
    type: Literal["tool_call"]
    call_id: str
    name: str
    arguments_json: str = Field(
        ...,
        description="Tool arguments as JSON-encoded string (OpenAI strict mode compliant)"
    )


class ResultToolResultContent(StrictBaseModel):
    """Tool result content for structured outputs - strict, no defaults.

    All fields are required. Use None for unused fields.
    """
    type: Literal["tool_result"]
    call_id: str
    result_text: str | None = Field(...)
    result_json_str: str | None = Field(
        ...,
        description="Tool result as JSON-encoded string (for arbitrary structures)"
    )
    mime_type: str | None = Field(...)
    data_b64: str | None = Field(...)


class ResultJsonContent(StrictBaseModel):
    """JSON content for structured outputs - strict, no defaults."""
    type: Literal["json"]
    value_json: str = Field(
        ...,
        description="JSON content as encoded string (for arbitrary structures)"
    )


# ---- Union type for discriminated content ----

ResultContent = (
    ResultTextContent
    | ResultImageContent
    | ResultAudioContent
    | ResultFileContent
    | ResultScreenshotContent
    | ResultToolCallContent
    | ResultToolResultContent
    | ResultJsonContent
)
