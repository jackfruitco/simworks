"""
Public API surface for simcore.ai.schemas

This package re-exports the core schema base classes (StrictBaseModel, StrictOutputSchema),
the normalized DTOs, and OutputSchemaType. Downstream code should import from this
module rather than submodules to avoid tight coupling to internal layout.

Example:
    from simcore.ai.schemas import NormalizedAIResponse, OutputSchemaType
"""

from .base import StrictBaseModel, StrictOutputSchema, Boolish
from .types import (
    AttachmentItem,
    MessageItem,
    MetafieldItem,
    ToolItem,
    LLMRequest,
    LLMResponse,
    StreamChunk,
)

from .output_types import (
    OutputMessageItem,
    OutputMetafieldItem,
)

from .tools import CustomToolItem

__all__ = [
    "StrictBaseModel",
    "StrictOutputSchema",
    "Boolish",
    "AttachmentItem",
    "MessageItem",
    "MetafieldItem",
    "ToolItem",
    "LLMRequest",
    "LLMResponse",
    "StreamChunk",
    "CustomToolItem",
    "OutputMessageItem",
    "OutputMetafieldItem",
]