"""API schemas for lab order submission and response."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LabOrderSubmit(BaseModel):
    """Input schema for submitting signed lab orders."""

    orders: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of ordered test names (e.g. ['CBC', 'BMP', 'Chest X-Ray']). "
        "Each string must be non-empty. Maximum 50 orders per request.",
    )

    @field_validator("orders", mode="before")
    @classmethod
    def validate_order_lengths(cls, v: list) -> list:
        for item in v:
            if isinstance(item, str) and len(item) > 255:
                raise ValueError("Each order string must be at most 255 characters")
        return v


class LabOrdersOut(BaseModel):
    """Response returned after lab orders are accepted for processing."""

    status: Literal["accepted"] = Field(default="accepted", description="Request status")
    call_id: str | None = Field(
        default=None,
        description="Service call ID for tracking (null if enqueueing failed)",
    )
    orders: list[str] = Field(..., description="Orders accepted for processing")
