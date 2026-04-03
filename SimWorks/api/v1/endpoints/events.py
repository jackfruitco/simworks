"""Event endpoints for API v1.

Provides catch-up API for WebSocket event recovery after reconnection.
"""

from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import JWTAuth
from api.v1.schemas.common import PaginatedResponse
from api.v1.schemas.events import EventEnvelope
from api.v1.sse import stream_outbox_events
from api.v1.utils import get_simulation_for_user
from apps.chatlab.access import require_lab_access as require_chatlab_access
from apps.common.outbox import event_types as outbox_events
from apps.common.outbox.outbox import apply_outbox_cursor, order_outbox_queryset
from apps.common.ratelimit import api_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["events"], auth=JWTAuth())


def _require_chatlab_access(request: HttpRequest):
    return require_chatlab_access(request.auth, request=request)


@router.get(
    "/{simulation_id}/events/",
    response=PaginatedResponse[EventEnvelope],
    summary="List events for explicit catch-up / replay",
    description=(
        "Returns outbox events for a simulation using cursor-based pagination.\n\n"
        "Use this endpoint for **explicit** catch-up after reconnection or for\n"
        "replaying historical events.  The live SSE stream (``/events/stream/``)\n"
        "defaults to tail-only and does **not** replay.\n\n"
        "Delivery semantics are at-least-once.  Clients must deduplicate by\n"
        "``event_id``."
    ),
)
@api_rate_limit
def list_events(
    request: HttpRequest,
    simulation_id: int,
    cursor: str | None = Query(default=None, description="Cursor (event ID) to start after"),
    limit: int = Query(default=50, ge=1, le=100, description="Max events to return"),
) -> PaginatedResponse[EventEnvelope]:
    """List events for catch-up after WebSocket reconnection.

    Clients should:
    1. Track lastSeenEventId from WebSocket events
    2. On reconnect, call this endpoint with cursor=lastSeenEventId
    3. Process returned events and update lastSeenEventId
    4. Continue fetching while has_more is True
    """
    _require_chatlab_access(request)
    import uuid as uuid_module

    from apps.common.models import OutboxEvent

    user = request.auth

    # Verify user owns the simulation
    get_simulation_for_user(simulation_id, user, request=request)

    # Build queryset
    queryset = order_outbox_queryset(
        OutboxEvent.objects.filter(
            simulation_id=simulation_id,
        )
    )

    # Apply cursor-based pagination
    if cursor:
        try:
            cursor_uuid = uuid_module.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format: must be a valid UUID") from None

        # Get the created_at of the cursor event
        try:
            cursor_event = OutboxEvent.objects.get(id=cursor_uuid, simulation_id=simulation_id)
            queryset = apply_outbox_cursor(queryset, cursor_event)
        except OutboxEvent.DoesNotExist:
            raise HttpError(400, "Invalid cursor: event not found") from None

    # Fetch one extra to check for more
    events = list(queryset[: limit + 1])
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    # Determine next cursor
    next_cursor = str(events[-1].id) if has_more and events else None

    # Enrich message.item.created payloads with canonical media metadata
    from apps.chatlab.media_payloads import build_message_media_payload, payload_message_id
    from apps.chatlab.models import Message

    message_ids = []
    for event in events:
        if outbox_events.canonical_event_type(event.event_type) != outbox_events.MESSAGE_CREATED:
            continue
        payload = event.payload or {}
        msg_id = payload_message_id(payload)
        if msg_id is not None:
            message_ids.append(msg_id)

    messages_by_id = {}
    if message_ids:
        for msg in Message.objects.filter(
            simulation_id=simulation_id,
            id__in=message_ids,
        ).prefetch_related("media"):
            messages_by_id[msg.id] = msg

    # Convert to envelope format
    items = []
    for event in events:
        payload = dict(event.payload or {})
        if outbox_events.canonical_event_type(event.event_type) == outbox_events.MESSAGE_CREATED:
            msg_id = payload_message_id(payload)
            msg = messages_by_id.get(msg_id) if msg_id is not None else None
            if msg is not None:
                payload.update(build_message_media_payload(msg, request=request))
            else:
                payload.setdefault("media_list", [])
                payload.setdefault("mediaList", [])

        items.append(
            EventEnvelope(
                event_id=str(event.id),
                event_type=event.event_type,
                created_at=event.created_at,
                correlation_id=event.correlation_id,
                payload=payload,
            )
        )

    logger.debug(
        "events.catch_up",
        simulation_id=simulation_id,
        cursor=cursor,
        returned=len(items),
        has_more=has_more,
    )

    return PaginatedResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/{simulation_id}/events/stream/",
    summary="SSE stream for simulation events",
    description=(
        "Streams outbox events for a simulation using a canonical transport envelope.\n\n"
        "**Default (tail-only):** Omit ``cursor`` to receive only events created\n"
        "after the current tip — no historical replay.\n\n"
        "**Resume:** Pass ``cursor=<event_id>`` to stream events strictly after\n"
        "that checkpoint.  A stale or pruned cursor returns an SSE error frame\n"
        "with ``status: 410``; the client should re-bootstrap.\n\n"
        "**Explicit replay:** Pass ``replay=true`` (without a cursor) to replay\n"
        "all events from the beginning.\n\n"
        "Delivery semantics are **at-least-once**.  Clients must deduplicate by\n"
        "``event_id``."
    ),
)
@api_rate_limit
def stream_events(
    request: HttpRequest,
    simulation_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
    replay: bool = Query(
        default=False,
        description="When true (and cursor is omitted), replay all events from the beginning.",
    ),
    event_prefix: str | None = Query(
        default=None,
        description="Optional event_type prefix filter (e.g. patient. or simulation.)",
    ),
):
    _require_chatlab_access(request)
    user = request.auth
    get_simulation_for_user(simulation_id, user, request=request)
    return stream_outbox_events(
        simulation_id=simulation_id,
        cursor=cursor,
        replay=replay,
        event_type_prefix=event_prefix,
        sse_event_name="simulation",
        heartbeat_interval_seconds=10.0,
        heartbeat_comment=": keep-alive\n\n",
    )
