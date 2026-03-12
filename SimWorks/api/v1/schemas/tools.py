"""Tool schemas for API v1."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolOut(BaseModel):
    """Output schema for a simulation tool payload."""

    name: str = Field(..., description="Tool slug")
    display_name: str = Field(..., description="Human-readable tool name")
    data: list[dict[str, Any]] = Field(default_factory=list, description="Tool-specific data")
    is_generic: bool = Field(default=False, description="Whether this is a generic key-value tool")
    checksum: str = Field(..., description="Checksum for client cache validation")


class ToolListResponse(BaseModel):
    """Response for listing tool payloads."""

    items: list[ToolOut] = Field(..., description="Tool payloads")


class SignOrdersIn(BaseModel):
    """Input schema for lab order signing."""

    submitted_orders: list[str] = Field(
        default_factory=list,
        description="Lab orders to sign and enqueue",
    )


class SignOrdersOut(BaseModel):
    """Response for lab order signing."""

    status: Literal["ok"] = Field(default="ok", description="Request status")
    orders: list[str] = Field(default_factory=list, description="Orders accepted for processing")

