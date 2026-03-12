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

    **Supported Event Types**:
    - ``chat.message_created`` - New chat message from patient or user
    - ``message_status_update`` - Outgoing message status changed (sent/delivered/failed)
    - ``metadata.created`` - Metadata created (labs, radiology, demographics, assessments)
    - ``feedback.created`` - Simulation feedback/hotwash item created
    - ``feedback.failed`` / ``feedback.retrying`` - Feedback generation lifecycle events
    - ``typing.started`` / ``typing.stopped`` - Typing indicators
    - ``simulation.ended`` - Simulation completed
    - ``simulation.state_changed`` - Simulation status changed

    **Event Payload Structures**:

    ``chat.message_created``:
    - ``message_id`` (int): Message database ID
    - ``content`` (str): Message text content
    - ``role`` (str): Message role (user, assistant, etc.)
    - ``is_from_ai`` (bool): Whether message is AI-generated
    - ``display_name`` (str): Display name for sender
    - ``timestamp`` (str): ISO timestamp
    - ``image_requested`` (bool, optional): Whether images were requested
    - ``media_list`` (list, optional): Canonical media metadata with absolute URLs
    - ``mediaList`` (list, optional): Compatibility alias for web clients

    ``metadata.created``:
    - ``metadata_id`` (int): Metadata database ID
    - ``kind`` (str): Metadata type (lab_result, rad_result, patient_demographics, etc.)
    - ``key`` (str): Metadata key
    - ``value`` (str): Metadata value

    ``feedback.created``:
    - ``feedback_id`` (int): Feedback database ID
    - ``key`` (str): Feedback key (e.g., hotwash_correct_diagnosis)
    - ``value`` (str): Feedback value
    """

    event_id: str = Field(
        ...,
        description="Unique event identifier (UUID) for deduplication",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    event_type: str = Field(
        ...,
        description=(
            "Event type: chat.message_created, message_status_update, metadata.created, "
            "feedback.created, feedback.failed, feedback.retrying, "
            "typing.started, typing.stopped, simulation.ended, simulation.state_changed"
        ),
        examples=["chat.message_created", "message_status_update", "simulation.state_changed"],
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
        description="Event-specific payload data (structure varies by event_type)",
    )
