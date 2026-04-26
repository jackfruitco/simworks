"""Modifier schemas for API v1."""

from pydantic import BaseModel, Field


class ModifierOut(BaseModel):
    key: str = Field(..., description="Unique modifier key")
    label: str = Field(..., description="Display label")
    description: str = Field(..., description="Human-readable description")


class SelectionConfigOut(BaseModel):
    mode: str = Field(..., description="Selection mode: single or multiple")
    required: bool = Field(..., description="Whether a selection is required")


class ModifierGroupOut(BaseModel):
    key: str = Field(..., description="Group key")
    label: str = Field(..., description="Display label")
    description: str = Field(..., description="Group description")
    selection: SelectionConfigOut = Field(..., description="Selection constraints")
    modifiers: list[ModifierOut] = Field(..., description="Available modifiers in this group")
