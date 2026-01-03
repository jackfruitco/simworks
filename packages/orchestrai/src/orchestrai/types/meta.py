"""
Canonical metadata types for OpenAI Structured Outputs compliance.

This module provides strict, OpenAI-compatible alternatives to dict[str, Any]
metadata fields, which violate OpenAI's additionalProperties: false requirement.

Usage:
    Instead of:
        item_meta: dict[str, Any] = Field(default_factory=dict)

    Use:
        item_meta: list[Metafield] = Field(default_factory=list)

    This ensures the schema is closed (additionalProperties: false) and
    compatible with OpenAI Structured Outputs strict mode.
"""

from pydantic import Field

from .base import StrictBaseModel

__all__ = ["Metafield", "HasItemMeta"]


class Metafield(StrictBaseModel):
    """
    Single key-value metadata entry for OpenAI-strict schemas.

    OpenAI Structured Outputs requires all objects to have additionalProperties: false.
    Using dict[str, Any] creates an open object, which is rejected in strict mode.

    Solution: Use list[Metafield] instead of dict[str, Any] for metadata bags.

    Fields:
        key: Metadata key (e.g., "type", "confidence", "source")
        value: Metadata value - limited to JSON primitives for strict compliance
               Supports: str | int | float | bool | None

    Example:
        # Old pattern (rejected by OpenAI strict mode):
        item_meta: dict[str, Any] = {"type": "diagnosis", "confidence": 0.95}

        # New pattern (OpenAI strict mode compliant):
        item_meta: list[Metafield] = [
            Metafield(key="type", value="diagnosis"),
            Metafield(key="confidence", value=0.95),
        ]

    Design Notes:
        - Empty list is allowed (default_factory=list)
        - Value type is a union of JSON primitives (no nested objects/arrays)
        - If complex nested values are needed, serialize to JSON string first
    """

    key: str = Field(
        ...,
        description="Metadata key identifier",
        min_length=1
    )

    value: str | int | float | bool | None = Field(
        ...,
        description="Metadata value - JSON primitive types only"
    )


class HasItemMeta(StrictBaseModel):
    """
    Mixin providing OpenAI-strict item_meta field.

    Use this mixin for models that need metadata bags compatible with
    OpenAI Structured Outputs.

    Example:
        class MyOutputItem(HasItemMeta, StrictBaseModel):
            role: str
            content: list[OutputContent]
            # item_meta inherited from mixin
    """

    item_meta: list[Metafield] = Field(
        default_factory=list,
        description="Metadata entries as key-value pairs"
    )
