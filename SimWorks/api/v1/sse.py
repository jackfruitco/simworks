"""Shared SSE helpers for API v1 event streaming.

Stream semantics
----------------
* ``cursor=None`` (omitted) **without** ``replay=True`` → **tail-only**.
  The stream starts after the current latest outbox event; only events
  created *after* the connection opens will be delivered.
* ``cursor=<event_id>`` → **resume** after that event.
* ``cursor=<stale/missing>`` → HTTP **410 Gone** so the client knows to
  re-bootstrap.
* ``replay=True`` (explicit) → stream from the very beginning.

Delivery semantics are **at-least-once**.  Clients must deduplicate by
``event_id``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
import uuid

from django.http import StreamingHttpResponse
from ninja.errors import HttpError

from apps.common.outbox.outbox import (
    apply_outbox_cursor,
    build_canonical_envelope,
    order_outbox_queryset,
)
from config.logging import get_logger

logger = get_logger(__name__)


def build_transport_envelope(event, *, enrich_payload=None) -> dict[str, Any]:
    """Build a canonical transport envelope for streamed outbox events.

    Delegates to :func:`~apps.common.outbox.outbox.build_canonical_envelope`.
    """
    return build_canonical_envelope(event, enrich_payload=enrich_payload)


def _make_message_media_enricher(simulation_id: int):
    """Return a payload-enricher callback for ``message.item.created`` events.

    The enricher fetches the related :class:`Message` with prefetched media
    and merges ``media_list`` / ``mediaList`` keys into the payload.
    """
    from apps.chatlab.media_payloads import build_message_media_payload, payload_message_id
    from apps.chatlab.models import Message
    from apps.common.outbox import event_types as outbox_events

    async def _enrich(event):
        if outbox_events.canonical_event_type(event.event_type) != outbox_events.MESSAGE_CREATED:
            return None  # no enrichment needed
        payload = dict(event.payload or {})
        msg_id = payload_message_id(payload)
        if msg_id is None:
            payload.setdefault("media_list", [])
            payload.setdefault("mediaList", [])
            return payload
        try:
            message = await Message.objects.prefetch_related("media").aget(
                id=msg_id, simulation_id=simulation_id
            )
            payload.update(build_message_media_payload(message))
        except Message.DoesNotExist:
            payload.setdefault("media_list", [])
            payload.setdefault("mediaList", [])
        return payload

    return _enrich


def stream_outbox_events(
    *,
    simulation_id: int,
    cursor: str | None = None,
    replay: bool = False,
    event_type_prefix: str | None = None,
    sse_event_name: str = "simulation",
    heartbeat_interval_seconds: float | None = None,
    poll_interval_seconds: float = 1.0,
    heartbeat_comment: str = ": keep-alive\n\n",
    emit_named_heartbeat: bool = False,
) -> StreamingHttpResponse:
    """Create a ``StreamingHttpResponse`` for simulation outbox events.

    Stream semantics:

    * **cursor omitted + replay=False** → tail-only from current tip.
    * **cursor omitted + replay=True** → replay from the beginning.
    * **cursor=<uuid>** → resume strictly after that event.
    * **cursor=<stale/missing uuid>** → HTTP 410 Gone.
    """
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

    media_enricher = _make_message_media_enricher(simulation_id)

    async def event_stream():
        last_event = None

        if cursor_uuid is not None:
            # Explicit cursor — resolve the bookmark event.
            base_qs = OutboxEvent.objects.filter(simulation_id=simulation_id)
            if event_type_prefix:
                base_qs = base_qs.filter(event_type__startswith=event_type_prefix)
            base_qs = order_outbox_queryset(base_qs)
            last_event = await base_qs.filter(id=cursor_uuid).afirst()
            if last_event is None:
                # Stale / pruned cursor — tell the client to re-bootstrap.
                logger.warning(
                    "sse_stale_cursor",
                    simulation_id=simulation_id,
                    cursor=str(cursor_uuid),
                )
                yield 'event: error\ndata: {"error": "stale_cursor", "status": 410}\n\n'
                return
        elif not replay:
            # No cursor, no replay → tail-only: start after the latest event.
            base_qs = OutboxEvent.objects.filter(simulation_id=simulation_id)
            if event_type_prefix:
                base_qs = base_qs.filter(event_type__startswith=event_type_prefix)
            base_qs = order_outbox_queryset(base_qs)
            last_event = await base_qs.alast()
        # else: replay=True with no cursor → last_event stays None → full replay

        logger.info(
            "sse_stream_opened",
            simulation_id=simulation_id,
            cursor=str(cursor_uuid) if cursor_uuid else None,
            replay=replay,
            tail_from=str(last_event.id) if last_event else None,
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
                    enriched_payload = await media_enricher(event)
                    if enriched_payload is not None:
                        data = build_transport_envelope(
                            event,
                            enrich_payload=lambda _p, _ep=enriched_payload: _ep,
                        )
                    else:
                        data = build_transport_envelope(event)

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
