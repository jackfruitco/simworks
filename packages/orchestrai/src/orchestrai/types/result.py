# orchestrai/types/result.py
"""
Result-side message and metadata types for strict schema generation.

These types are used for:
- OpenAI Structured Outputs schema definitions
- Response validation/parsing
- Persistence routing

Key characteristics:
- Subclass StrictBaseModel (extra="forbid")
- NO defaults on fields (all required unless explicitly Optional)
- Generate strict JSON Schema with additionalProperties: false

DO NOT use these for construction - use Build* types instead.
"""

from pydantic import Field

from .base import StrictBaseModel
from .content import ContentRole
from .result_content import ResultContent

__all__ = (
    "ResultMessageItem",
    "ResultMetafield",
)


# ---- Result-side metadata ----


class ResultMetafield(StrictBaseModel):
    """
    Metadata field for structured outputs - strict, no defaults.

    OpenAI Structured Outputs requires all objects to have additionalProperties: false.
    Using list[ResultMetafield] instead of dict[str, Any] for metadata bags ensures compliance.
    """

    key: str = Field(..., min_length=1, description="Metadata key identifier")
    value: str | int | float | bool | None = Field(
        ..., description="Metadata value - JSON primitive types only"
    )

    __orm_model__ = "simcore.SimulationMetadata"


# ---- Result-side message item ----


class ResultMessageItem(StrictBaseModel):
    """
    Message item for structured outputs - strict, no defaults.

    Used in:
    - OpenAI Structured Outputs schema definitions
    - LLM response parsing/validation
    - Persistence routing

    All fields are required. Use empty list [] for item_meta if no metadata needed.
    """

    role: ContentRole
    content: list[ResultContent] = Field(..., min_length=1)
    item_meta: list[ResultMetafield] = Field(
        ..., description="Metadata entries as key-value pairs (use empty list [] if none)"
    )
