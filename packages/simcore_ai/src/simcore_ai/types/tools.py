# simcore_ai/types/tools.py
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import Field

from .base import StrictBaseModel


# ---- Tool specs (request time) -------------------------------------------------------

class BaseLLMTool(StrictBaseModel):
    """
    Provider-agnostic tool declaration.
    - input_schema is a JSON Schema dict (compile with schema_compiler for provider quirks).
    """
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    strict: bool | None = None
    examples: list[dict[str, Any]] | None = None
    arguments: Optional[dict[str, Any]] = None


LLMToolChoice = Literal["auto", "none"] | str


# ---- Normalized record of a tool call (response time) --------------------------------

class LLMToolCall(StrictBaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


# ---- Streaming delta for tool calls --------------------------------------------------

class LLMToolCallDelta(StrictBaseModel):
    """Chunked updates to a single tool call during streaming."""
    call_id: str | None = None
    name: str | None = None
    arguments_delta_json: str | None = None  # JSON string delta
