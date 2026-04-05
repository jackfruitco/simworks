"""Event schemas for API v1.

Defines the canonical event envelope used across ChatLab REST/WS replay
flows and TrainerLab REST/SSE replay flows.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from apps.common.outbox import event_types


class EventEnvelope(BaseModel):
    """Canonical event envelope — identical across every transport.

    This schema is the single source of truth for event serialization.
    The same ``EventEnvelope`` is used by:

    * **ChatLab REST replay** (``GET /simulations/{id}/events/``)
    * **TrainerLab SSE streaming** (``GET /trainerlab/simulations/{id}/events/stream/``)
    * **WebSocket delivery** (outbox drain → channel layer)

    Delivery semantics
    ------------------
    * **At-least-once**: duplicates are expected.  Clients must
      deduplicate by ``event_id`` (which is the outbox row UUID and
      therefore stable across retries).
    * **Cursor-based ordering**: events are ordered by
      ``(created_at, id)`` with a stable tie-breaker.

    Bootstrap integration
    ---------------------
    Bootstrap responses include a durable event anchor field:

    * **ChatLab**: ``SimulationOut.latest_event_id`` (``GET /simulations/{id}/``)
    * **TrainerLab**: ``TrainerRestViewModelOut.runtime_snapshot.latest_event_cursor``
      (``GET /trainerlab/simulations/{id}/state/``)

    ChatLab clients use ``last_event_id`` during the WebSocket
    ``session.hello`` / ``session.resume`` handshake for durable replay.
    TrainerLab clients pass ``latest_event_cursor`` to the SSE stream.

    Canonical outbox event types follow a strict three-segment contract:
    ``domain.subject.action``.
    Domains are limited to ``simulation``, ``patient``, ``message``,
    ``feedback``, and ``guard``.
    Canonical API output emits only those registry-defined names.

    **Supported Event Types**:
    - ``message.item.created`` - New chat message from patient or user
    - ``message.delivery.updated`` - Outgoing message status changed (sent/delivered/failed)
    - ``patient.metadata.created`` - Metadata created (labs, radiology, demographics, assessments)
    - ``patient.results.updated`` - Patient results panel content refreshed
    - ``feedback.item.created`` - Simulation feedback/hotwash item created
    - ``feedback.generation.failed`` / ``feedback.generation.updated`` - Feedback generation lifecycle events
    - ``simulation.status.updated`` - Simulation status changed
    - ``simulation.snapshot.updated`` - TrainerLab runtime snapshot changed
    - ``patient.*`` - Patient domain object lifecycle events

    **Event Payload Structures**:

    ``message.item.created``:
    - ``message_id`` (int): Message database ID
    - ``content`` (str): Message text content
    - ``role`` (str): Message role (user, assistant, etc.)
    - ``is_from_ai`` (bool): Whether message is AI-generated
    - ``display_name`` (str): Display name for sender
    - ``timestamp`` (str): ISO timestamp
    - ``image_requested`` (bool, optional): Whether images were requested
    - ``media_list`` (list, optional): Canonical media metadata with absolute URLs

    ``patient.metadata.created``:
    - ``metadata_id`` (int): Metadata database ID
    - ``kind`` (str): Metadata type (lab_result, rad_result, patient_demographics, etc.)
    - ``key`` (str): Metadata key
    - ``value`` (str): Metadata value

    ``feedback.item.created``:
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
        description=event_types.event_type_description(),
        examples=event_types.event_type_examples(),
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


class EventReplayResponse(BaseModel):
    """ChatLab durable replay response."""

    items: list[EventEnvelope] = Field(
        ...,
        description="List of replayable durable events in canonical order",
    )
    next_event_id: str | None = Field(
        default=None,
        description="Event ID anchor for the next page, null if no more items remain",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    has_more: bool = Field(
        ...,
        description="Whether more durable events exist beyond this page",
    )
