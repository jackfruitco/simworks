"""Shared SSE helpers for API v1 event streaming.

Stream semantics
----------------
* ``cursor=None`` (omitted) **without** ``replay=True`` → **tail-only**.
  The stream starts after the current latest outbox event; only events
  created *after* the connection opens will be delivered.
* ``cursor=<event_id>`` → **resume** after that event.
* ``cursor=<stale/missing>`` → HTTP **410 Gone** so the client knows to
  re-bootstrap.  The 410 is returned *before* any stream bytes are sent —
  no successful ``200 OK`` stream is opened for stale or pruned cursors.
* ``replay=True`` (explicit) → stream from the very beginning.

Delivery semantics are **at-least-once**.  Clients must deduplicate by
``event_id``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
import uuid

from django.http import StreamingHttpResponse
from ninja.errors import HttpError

from apps.common.outbox.outbox import (
    apply_outbox_cursor,
    build_canonical_envelope,
    order_outbox_queryset,
)
from config.logging import get_logger

if TYPE_CHECKING:
    from apps.common.models import OutboxEvent

logger = get_logger(__name__)

STALE_CURSOR_DETAIL = (
    "Stale cursor: event no longer available; client must re-bootstrap"
)


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


def _build_outbox_base_queryset(*, simulation_id: int, event_type_prefix: str | None = None):
    """Return a base (unordered) OutboxEvent queryset for the given simulation."""
    from apps.common.models import OutboxEvent

    qs = OutboxEvent.objects.filter(simulation_id=simulation_id)
    if event_type_prefix:
        qs = qs.filter(event_type__startswith=event_type_prefix)
    return qs


def _parse_cursor_uuid(cursor: str | None) -> uuid.UUID | None:
    """Parse a cursor string to UUID, raising HttpError(400) on invalid format."""
    if not cursor:
        return None
    try:
        return uuid.UUID(cursor)
    except ValueError:
        raise HttpError(400, "Invalid cursor format") from None


def resolve_outbox_stream_anchor(
    *,
    simulation_id: int,
    cursor: str | None = None,
    replay: bool = False,
    event_type_prefix: str | None = None,
) -> OutboxEvent | None:
    """Resolve the initial stream anchor synchronously (runs BEFORE response is opened).

    Returns:
        The anchor event — the stream will deliver only events *after* this.
        ``None`` means replay from the very beginning.

    Raises:
        HttpError(400): invalid cursor UUID format.
        HttpError(410): cursor was a valid UUID but the event no longer exists.
    """
    cursor_uuid = _parse_cursor_uuid(cursor)
    base_qs = _build_outbox_base_queryset(
        simulation_id=simulation_id, event_type_prefix=event_type_prefix
    )

    if cursor_uuid is not None:
        cursor_event = order_outbox_queryset(base_qs).filter(id=cursor_uuid).first()
        if cursor_event is None:
            logger.warning(
                "sse_stale_cursor",
                simulation_id=simulation_id,
                cursor=str(cursor_uuid),
            )
            raise HttpError(410, STALE_CURSOR_DETAIL)
        return cursor_event

    if replay:
        return None  # Full replay from beginning

    # Default: tail-only — start after the current latest event.
    return order_outbox_queryset(base_qs).last()


async def aresolve_outbox_stream_anchor(
    *,
    simulation_id: int,
    cursor: str | None = None,
    replay: bool = False,
    event_type_prefix: str | None = None,
) -> OutboxEvent | None:
    """Async variant of :func:`resolve_outbox_stream_anchor`.

    Used by async endpoints (e.g. TrainerLab SSE) that need to await DB access.

    Raises:
        HttpError(400): invalid cursor UUID format.
        HttpError(410): cursor was a valid UUID but the event no longer exists.
    """
    cursor_uuid = _parse_cursor_uuid(cursor)
    base_qs = _build_outbox_base_queryset(
        simulation_id=simulation_id, event_type_prefix=event_type_prefix
    )

    if cursor_uuid is not None:
        cursor_event = await order_outbox_queryset(base_qs).filter(id=cursor_uuid).afirst()
        if cursor_event is None:
            logger.warning(
                "sse_stale_cursor",
                simulation_id=simulation_id,
                cursor=str(cursor_uuid),
            )
            raise HttpError(410, STALE_CURSOR_DETAIL)
        return cursor_event

    if replay:
        return None

    return await order_outbox_queryset(base_qs).alast()


def build_outbox_events_stream_response(
    *,
    simulation_id: int,
    last_event: OutboxEvent | None,
    cursor: str | None = None,
    event_type_prefix: str | None = None,
    sse_event_name: str = "simulation",
    heartbeat_interval_seconds: float | None = None,
    poll_interval_seconds: float = 1.0,
    heartbeat_comment: str = ": keep-alive\n\n",
    emit_named_heartbeat: bool = False,
) -> StreamingHttpResponse:
    """Build the SSE ``StreamingHttpResponse`` for a pre-resolved stream anchor.

    The caller is responsible for resolving ``last_event`` via
    :func:`resolve_outbox_stream_anchor` (or its async counterpart) *before*
    calling this function.  Any stale-cursor or format errors must be raised
    before this call — this function always returns a ``200 OK`` stream.
    """
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    if heartbeat_interval_seconds is not None and heartbeat_interval_seconds <= 0:
        raise ValueError("heartbeat_interval_seconds must be positive")

    media_enricher = _make_message_media_enricher(simulation_id)

    logger.info(
        "sse_stream_opened",
        simulation_id=simulation_id,
        cursor=cursor,
        tail_from=str(last_event.id) if last_event else None,
    )

    async def event_stream():
        nonlocal last_event

        # Send the first byte immediately so nginx / Cloudflare see an active
        # upstream and time-to-first-byte is not delayed by the first poll.
        yield heartbeat_comment
        last_signal_at = time.monotonic()

        try:
            while True:
                try:
                    queryset = _build_outbox_base_queryset(
                        simulation_id=simulation_id,
                        event_type_prefix=event_type_prefix,
                    )
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

    Resolves the stream anchor synchronously (raising HTTP 400/410 before any
    bytes are sent) then delegates to
    :func:`build_outbox_events_stream_response`.

    Stream semantics:

    * **cursor omitted + replay=False** → tail-only from current tip.
    * **cursor omitted + replay=True** → replay from the beginning.
    * **cursor=<uuid>** → resume strictly after that event.
    * **cursor=<stale/missing uuid>** → HTTP 410 Gone.
    """
    last_event = resolve_outbox_stream_anchor(
        simulation_id=simulation_id,
        cursor=cursor,
        replay=replay,
        event_type_prefix=event_type_prefix,
    )
    return build_outbox_events_stream_response(
        simulation_id=simulation_id,
        last_event=last_event,
        cursor=cursor,
        event_type_prefix=event_type_prefix,
        sse_event_name=sse_event_name,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_comment=heartbeat_comment,
        emit_named_heartbeat=emit_named_heartbeat,
    )
