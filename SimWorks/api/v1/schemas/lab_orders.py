"""API schemas for lab order submission and response."""

from typing import Literal

from pydantic import BaseModel, Field


class LabOrderSubmit(BaseModel):
    """Input schema for submitting signed lab orders."""

    orders: list[str] = Field(
        ...,
        min_length=1,
        description="List of ordered test names (e.g. ['CBC', 'BMP', 'Chest X-Ray']). "
        "Each string must be non-empty.",
    )


class LabOrdersOut(BaseModel):
    """Response returned after lab orders are accepted for processing."""

    status: Literal["accepted"] = Field(default="accepted", description="Request status")
    call_id: str | None = Field(
        default=None,
        description="Service call ID for tracking (null if enqueueing failed)",
    )
    orders: list[str] = Field(..., description="Orders accepted for processing")
