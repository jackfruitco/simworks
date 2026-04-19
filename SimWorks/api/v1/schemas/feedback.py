"""Feedback schemas for API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackOut(BaseModel):
    """Output schema for a user feedback submission (user-facing)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    user_id: int | None = None
    account_id: int | None = None
    simulation_id: int | None = None
    conversation_id: int | None = None
    lab_type: str = ""
    category: str
    source: str
    status: str
    severity: str = ""
    title: str = ""
    body: str
    rating: int | None = None
    allow_follow_up: bool = True
    client_platform: str = "unknown"
    client_version: str = ""


class FeedbackStaffOut(FeedbackOut):
    """Output schema for staff — extends FeedbackOut with internal fields."""

    internal_notes: str = ""
    resolved_at: datetime | None = None
    resolved_by_id: int | None = None
    request_id: str = ""
    session_identifier: str = ""
    os_version: str = ""
    device_model: str = ""
    context_json: dict = Field(default_factory=dict)


class FeedbackCreate(BaseModel):
    """Input schema for creating a feedback submission."""

    category: Literal[
        "bug_report", "ux_issue", "simulation_content", "feature_request", "other"
    ] = Field(..., description="Feedback category")
    body: str = Field(
        ...,
        description="Full feedback text",
        min_length=1,
        max_length=10_000,
    )
    title: str | None = Field(
        default=None,
        description="Short summary (optional)",
        max_length=255,
    )
    simulation_id: int | None = Field(
        default=None,
        description="Simulation this feedback is scoped to (optional)",
    )
    conversation_id: int | None = Field(
        default=None,
        description="Conversation within the simulation (optional)",
    )
    rating: int | None = Field(
        default=None,
        description="Optional 1-5 rating",
        ge=1,
        le=5,
    )
    allow_follow_up: bool = Field(
        default=True,
        description="Whether the user consents to follow-up contact",
    )
    context: dict | None = Field(
        default=None,
        description="Optional client-provided metadata dict (max ~10 KB serialised)",
    )


class FeedbackCategoryOut(BaseModel):
    """A single feedback category choice."""

    value: str
    label: str


class FeedbackListResponse(BaseModel):
    """Paginated list of feedback submissions."""

    items: list[FeedbackOut]
    count: int
    total: int


class FeedbackStaffListResponse(BaseModel):
    """Paginated staff list of feedback submissions."""

    items: list[FeedbackStaffOut]
    count: int
    total: int


def feedback_to_out(fb) -> FeedbackOut:
    return FeedbackOut.model_validate(fb)


def feedback_to_staff_out(fb) -> FeedbackStaffOut:
    return FeedbackStaffOut.model_validate(fb)
