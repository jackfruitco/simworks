"""Event schemas for API v1.

Defines the WebSocket event envelope format used for catch-up API.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """WebSocket event envelope format.

    Matches the standardized envelope format defined in CLAUDE.md.
    Used for both WebSocket delivery and catch-up API responses.
    """

    event_id: str = Field(
        ...,
        description="Unique event identifier (UUID) for deduplication",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    event_type: str = Field(
        ...,
        description="Event type (e.g., 'message.created', 'typing.started')",
        examples=["message.created"],
    )
    created_at: datetime = Field(
        ...,
        description="Event timestamp (ISO 8601)",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Request correlation ID for tracing",
        examples=["abc123-def456"],
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Event-specific payload data",
    )
