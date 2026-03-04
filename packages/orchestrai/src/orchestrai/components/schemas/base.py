"""Minimal schema compatibility bases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseOutputSchema(BaseModel):
    """Legacy compatibility base for output schemas."""

    model_config = ConfigDict(extra="forbid")


class BaseOutputItem(BaseOutputSchema):
    """Legacy compatibility base for nested schema items."""
