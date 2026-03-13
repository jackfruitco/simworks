"""Shared SSE helpers for API v1 event streaming."""

from __future__ import annotations

from datetime import UTC
import json
import time
from typing import Any
import uuid

from django.db.models import Q
from django.http import StreamingHttpResponse
from ninja.errors import HttpError

from api.v1.schemas.events import EventEnvelope
from apps.common.outbox.outbox import apply_outbox_cursor, order_outbox_queryset


def build_transport_envelope(event) -> dict[str, Any]:
    """Build a common transport envelope for streamed outbox events."""
    envelope = EventEnvelope(
        event_id=str(event.id),
        event_type=event.event_type,
        created_at=event.created_at,
        correlation_id=event.correlation_id,
        payload=event.payload,
    )
    return envelope.model_dump(mode="json")


def stream_outbox_events(
    *,
    simulation_id: int,
    cursor: str | None = None,
    event_type_prefix: str | None = None,
    sse_event_name: str = "simulation",
) -> StreamingHttpResponse:
    """Create a StreamingHttpResponse for simulation outbox events."""
    from apps.common.models import OutboxEvent

    base_queryset = OutboxEvent.objects.filter(simulation_id=simulation_id)
    if event_type_prefix:
        base_queryset = base_queryset.filter(event_type__startswith=event_type_prefix)
    base_queryset = order_outbox_queryset(base_queryset)

    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None

        cursor_event = base_queryset.filter(id=cursor_uuid).first()
        if cursor_event is None:
            raise HttpError(400, "Invalid cursor")

    def event_stream():
        last_event = cursor_event if cursor else None

        while True:
            queryset = OutboxEvent.objects.filter(simulation_id=simulation_id)
            if event_type_prefix:
                queryset = queryset.filter(event_type__startswith=event_type_prefix)
            queryset = order_outbox_queryset(queryset)

            if last_event is not None:
                queryset = apply_outbox_cursor(queryset, last_event)

            events = list(queryset[:100])
            for event in events:
                data = build_transport_envelope(event)
                data["created_at"] = event.created_at.astimezone(UTC).isoformat()

                yield f"id: {event.id}\n"
                yield f"event: {sse_event_name}\n"
                yield f"data: {json.dumps(data)}\n\n"
                last_event = event

            yield ": keepalive\n\n"
            time.sleep(1)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
