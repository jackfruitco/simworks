"""
Public API surface for simcore.ai.schemas

This package re-exports the core schema base classes (StrictBaseModel, StrictOutputSchema),
the normalized DTOs, and OutputSchemaType. Downstream code should import from this
module rather than submodules to avoid tight coupling to internal layout.

Example:
    from simcore.ai.schemas import NormalizedAIResponse, OutputSchemaType
"""

from .base import StrictBaseModel, StrictOutputSchema
from .normalized_types import (
    OutputSchemaType,
    NormalizedAIMessage,
    NormalizedAIMetadata,
    NormalizedAIRequest,
    NormalizedAIResponse,
    NormalizedStreamChunk,
)

__all__ = [
    "StrictBaseModel",
    "StrictOutputSchema",
    "OutputSchemaType",
    "NormalizedAIMessage",
    "NormalizedAIMetadata",
    "NormalizedAIRequest",
    "NormalizedAIResponse",
    "NormalizedStreamChunk",
]