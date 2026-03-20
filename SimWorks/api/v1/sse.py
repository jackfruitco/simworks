"""Shared SSE helpers for API v1 event streaming."""

from __future__ import annotations

import asyncio
from datetime import UTC
import json
import time
from typing import Any
import uuid

from django.http import StreamingHttpResponse
from ninja.errors import HttpError

from api.v1.schemas.events import EventEnvelope
from apps.common.outbox.outbox import apply_outbox_cursor, order_outbox_queryset
from config.logging import get_logger

logger = get_logger(__name__)


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
    heartbeat_interval_seconds: float | None = None,
    poll_interval_seconds: float = 1.0,
    heartbeat_comment: str = ": keep-alive\n\n",
    emit_named_heartbeat: bool = False,
) -> StreamingHttpResponse:
    """Create a StreamingHttpResponse for simulation outbox events."""
    from apps.common.models import OutboxEvent

    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    if heartbeat_interval_seconds is not None and heartbeat_interval_seconds <= 0:
        raise ValueError("heartbeat_interval_seconds must be positive")

    # Validate cursor UUID format eagerly (before the generator starts).
    cursor_uuid: uuid.UUID | None = None
    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None

    async def event_stream():
        # Resolve cursor event inside the async generator so the DB lookup is async.
        # A stale/missing cursor silently streams from the beginning — no 400 to clients
        # reconnecting after an event has been pruned.
        last_event = None
        if cursor_uuid is not None:
            base_qs = OutboxEvent.objects.filter(simulation_id=simulation_id)
            if event_type_prefix:
                base_qs = base_qs.filter(event_type__startswith=event_type_prefix)
            base_qs = order_outbox_queryset(base_qs)
            last_event = await base_qs.filter(id=cursor_uuid).afirst()

        logger.info(
            "sse_stream_opened",
            simulation_id=simulation_id,
            cursor=str(cursor_uuid) if cursor_uuid else None,
        )

        # Send the first byte immediately so nginx / Cloudflare see an active upstream
        # and time-to-first-byte is not delayed by the first poll interval.
        yield heartbeat_comment
        last_signal_at = time.monotonic()

        try:
            while True:
                try:
                    queryset = OutboxEvent.objects.filter(simulation_id=simulation_id)
                    if event_type_prefix:
                        queryset = queryset.filter(event_type__startswith=event_type_prefix)
                    queryset = order_outbox_queryset(queryset)

                    if last_event is not None:
                        queryset = apply_outbox_cursor(queryset, last_event)

                    events = [e async for e in queryset[:100]]
                except (asyncio.CancelledError, GeneratorExit):
                    logger.debug("sse_stream_cancelled", simulation_id=simulation_id)
                    return
                except Exception:
                    logger.exception(
                        "sse_stream_db_error",
                        simulation_id=simulation_id,
                    )
                    break

                for event in events:
                    data = build_transport_envelope(event)
                    data["created_at"] = event.created_at.astimezone(UTC).isoformat()

                    yield f"id: {event.id}\n"
                    yield f"event: {sse_event_name}\n"
                    yield f"data: {json.dumps(data)}\n\n"
                    last_event = event
                    last_signal_at = time.monotonic()

                now = time.monotonic()
                if heartbeat_interval_seconds is None or (
                    now - last_signal_at >= heartbeat_interval_seconds
                ):
                    yield heartbeat_comment
                    if emit_named_heartbeat:
                        yield "event: heartbeat\ndata: {}\n\n"
                    last_signal_at = now
                    logger.debug("sse_heartbeat_sent", simulation_id=simulation_id)

                await asyncio.sleep(poll_interval_seconds)
        except (asyncio.CancelledError, GeneratorExit):
            logger.debug("sse_stream_cancelled", simulation_id=simulation_id)
            return
        finally:
            logger.info("sse_stream_closed", simulation_id=simulation_id)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response
