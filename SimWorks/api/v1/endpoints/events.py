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
from apps.chatlab.events import build_chatlab_event_envelope, build_chatlab_transport_envelope
from apps.common.outbox.outbox import apply_outbox_cursor, order_outbox_queryset
from apps.common.ratelimit import api_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["events"], auth=JWTAuth())


@router.get(
    "/{simulation_id}/events/",
    response=PaginatedResponse[EventEnvelope],
    summary="List events for catch-up",
    description=(
        "Returns events for a simulation, enabling clients to catch up on missed "
        "WebSocket events after reconnection. Uses cursor-based pagination with "
        "UUID event IDs as cursors."
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
    import uuid as uuid_module

    from apps.common.models import OutboxEvent

    user = request.auth

    # Verify user owns the simulation
    get_simulation_for_user(simulation_id, user)

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

    items = [
        EventEnvelope(**build_chatlab_event_envelope(event, request=request)) for event in events
    ]

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
        "Streams outbox events for a simulation using a common transport envelope. "
        "Optionally filter by event type prefix."
    ),
)
@api_rate_limit
def stream_events(
    request: HttpRequest,
    simulation_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
    event_prefix: str | None = Query(
        default=None,
        description="Optional event_type prefix filter (e.g. trainerlab.)",
    ),
):
    user = request.auth
    get_simulation_for_user(simulation_id, user)
    return stream_outbox_events(
        simulation_id=simulation_id,
        cursor=cursor,
        event_type_prefix=event_prefix,
        envelope_builder=lambda event: build_chatlab_transport_envelope(event, request=request),
        sse_event_name="simulation",
        heartbeat_interval_seconds=10.0,
        heartbeat_comment=": keep-alive\n\n",
    )
