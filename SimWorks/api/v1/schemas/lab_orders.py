"""API schemas for lab order submission and response."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

LAB_ORDER_MAX_ITEMS = 50
LAB_ORDER_MAX_ITEM_LENGTH = 255
LAB_ORDER_LIST_DESCRIPTION = (
    "List of ordered test names (e.g. ['CBC', 'BMP', 'Chest X-Ray']). "
    "Each string must be non-empty. Maximum 50 orders per request."
)
LabOrderItem = Annotated[str, Field(max_length=LAB_ORDER_MAX_ITEM_LENGTH)]


def lab_order_list_field(*, description: str = LAB_ORDER_LIST_DESCRIPTION):
    """Return shared field metadata for lab-order request payloads."""
    return Field(
        ...,
        min_length=1,
        max_length=LAB_ORDER_MAX_ITEMS,
        description=description,
    )


class LabOrderSubmit(BaseModel):
    """Input schema for submitting signed lab orders."""

    orders: list[LabOrderItem] = lab_order_list_field()


class LabOrdersOut(BaseModel):
    """Response returned after lab orders are accepted for processing."""

    status: Literal["accepted"] = Field(default="accepted", description="Request status")
    call_id: str | None = Field(
        default=None,
        description="Service call ID for tracking (null if enqueueing failed)",
    )
    orders: list[str] = Field(..., description="Orders accepted for processing")
