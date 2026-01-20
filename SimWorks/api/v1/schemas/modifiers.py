"""Modifier schemas for API v1."""

from pydantic import BaseModel, Field


class ModifierOut(BaseModel):
    """Individual modifier option."""

    key: str = Field(..., description="Unique modifier key")
    description: str = Field(..., description="Human-readable description")


class ModifierGroupOut(BaseModel):
    """Group of related modifiers."""

    group: str = Field(..., description="Group name")
    description: str = Field(..., description="Group description")
    modifiers: list[ModifierOut] = Field(..., description="Available modifiers in this group")
