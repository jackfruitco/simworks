"""Tool-related DTOs for simcore-ai.

This module defines data transfer objects (DTOs) related to tools used within simcore-ai,
including backend-agnostic tool declarations at request time, normalized tool call records
at response time, and streaming deltas for tool calls.
"""

from typing import Any, Literal, TypeAlias

from pydantic import Field

from .base import StrictBaseModel


__all__ = ["BaseLLMTool", "LLMToolChoice", "LLMToolCall", "LLMToolCallDelta"]


# ---- Tool specs (request time) -------------------------------------------------------

class BaseLLMTool(StrictBaseModel):
    """
    Provider-agnostic tool declaration used at request time.
    Defines the tool's name, optional description, input schema, strictness,
    examples, and arguments.
    """
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for tool arguments; interpreted by backend codecs.")
    strict: bool | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)


LLMToolChoice: TypeAlias = Literal["auto", "none"] | str


# ---- Normalized record of a tool call (response time) --------------------------------

class LLMToolCall(StrictBaseModel):
    """Normalized record of a tool call at response time."""
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


# ---- Streaming delta for tool calls --------------------------------------------------

class LLMToolCallDelta(StrictBaseModel):
    """Chunked updates to a single tool call during streaming responses."""
    call_id: str | None = None
    name: str | None = None
    arguments_delta_json: str | None = None  # JSON string delta
