"""Common schemas for API v1.

Includes error responses (RFC 7807) and pagination schemas.
"""

from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """RFC 7807-inspired error response format.

    All API errors should return this format for consistency.
    """

    type: str = Field(
        ...,
        description="Error type identifier (e.g., 'validation_error', 'not_found')",
        examples=["validation_error"],
    )
    title: str = Field(
        ...,
        description="Short human-readable error title",
        examples=["Invalid input"],
    )
    status: int = Field(
        ...,
        description="HTTP status code",
        examples=[422],
    )
    detail: str = Field(
        ...,
        description="Detailed error explanation",
        examples=["Field 'content' is required"],
    )
    instance: str | None = Field(
        default=None,
        description="URI reference identifying the specific occurrence",
        examples=["/api/v1/messages/"],
    )
    correlation_id: str | None = Field(
        default=None,
        description="Request correlation ID for tracing",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based pagination response wrapper.

    Uses UUID-based cursors for stateless pagination.
    """

    items: list[T] = Field(
        ...,
        description="List of items in this page",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Cursor for fetching the next page, null if no more items",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    has_more: bool = Field(
        ...,
        description="Whether more items exist beyond this page",
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok", description="Service status")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Current server timestamp",
    )
