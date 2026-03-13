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

    initial_created_at = None
    initial_event_id = None
    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None

        cursor_event = base_queryset.filter(id=cursor_uuid).first()
        if cursor_event is None:
            raise HttpError(400, "Invalid cursor")
        initial_created_at = cursor_event.created_at
        initial_event_id = cursor_event.id

    def event_stream():
        last_created_at = initial_created_at
        last_event_id = initial_event_id

        while True:
            queryset = OutboxEvent.objects.filter(simulation_id=simulation_id)
            if event_type_prefix:
                queryset = queryset.filter(event_type__startswith=event_type_prefix)
            queryset = queryset.order_by("created_at", "id")

            if last_created_at is not None and last_event_id is not None:
                queryset = queryset.filter(
                    Q(created_at__gt=last_created_at)
                    | Q(created_at=last_created_at, id__gt=last_event_id)
                )

            events = list(queryset[:100])
            for event in events:
                data = build_transport_envelope(event)
                data["created_at"] = event.created_at.astimezone(UTC).isoformat()

                yield f"id: {event.id}\n"
                yield f"event: {sse_event_name}\n"
                yield f"data: {json.dumps(data)}\n\n"
                last_created_at = event.created_at
                last_event_id = event.id

            yield ": keepalive\n\n"
            time.sleep(1)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
