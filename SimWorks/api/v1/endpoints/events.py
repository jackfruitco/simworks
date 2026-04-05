"""ChatLab durable replay endpoints for API v1."""

from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import JWTAuth
from api.v1.schemas.events import EventEnvelope, EventReplayResponse
from api.v1.utils import get_simulation_for_user
from apps.chatlab.access import require_lab_access as require_chatlab_access
from apps.chatlab.media_payloads import build_message_media_payload, payload_message_id
from apps.chatlab.models import Message
from apps.chatlab.realtime import is_durable_event_type, parse_event_id
from apps.common.models import OutboxEvent
from apps.common.outbox import event_types as outbox_events
from apps.common.outbox.outbox import (
    apply_outbox_cursor,
    get_outbox_event_sync,
    order_outbox_queryset,
)
from apps.common.ratelimit import api_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["events"], auth=JWTAuth())


def _require_chatlab_access(request: HttpRequest):
    return require_chatlab_access(request.auth, request=request)


@router.get(
    "/{simulation_id}/events/",
    response=EventReplayResponse,
    summary="List replayable durable ChatLab events",
    description=(
        "Returns replayable durable ChatLab events in canonical order.\n\n"
        "Use this endpoint for explicit hard resync and offline replay after a\n"
        "ChatLab WebSocket session emits ``session.resync_required``. Normal\n"
        "reconnects should prefer WebSocket ``session.resume`` with\n"
        "``last_event_id``.\n\n"
        "Delivery semantics are at-least-once. Clients must deduplicate by\n"
        "``event_id``."
    ),
)
@api_rate_limit
def list_events(
    request: HttpRequest,
    simulation_id: int,
    last_event_id: str | None = Query(
        default=None,
        description="Replay anchor (event ID) to start strictly after",
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Max events to return"),
) -> EventReplayResponse:
    """List durable events for explicit ChatLab replay."""
    _require_chatlab_access(request)
    user = request.auth
    get_simulation_for_user(simulation_id, user, request=request)

    queryset = order_outbox_queryset(
        OutboxEvent.objects.filter(
            simulation_id=simulation_id,
        )
    )

    if last_event_id:
        try:
            parsed_last_event_id = parse_event_id(last_event_id)
        except Exception as exc:
            raise HttpError(400, "Invalid last_event_id: must be a valid UUID") from exc

        anchor_event = get_outbox_event_sync(
            simulation_id=simulation_id,
            event_id=parsed_last_event_id,
        )
        if anchor_event is None:
            raise HttpError(400, "Unknown last_event_id for this simulation")
        queryset = apply_outbox_cursor(queryset, anchor_event)

    events = [
        event
        for event in list(queryset[: limit + 1])
        if is_durable_event_type(event.event_type)
    ]
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    next_event_id = str(events[-1].id) if has_more and events else None

    message_ids = []
    for event in events:
        if outbox_events.canonical_event_type(event.event_type) != outbox_events.MESSAGE_CREATED:
            continue
        payload = event.payload or {}
        message_id = payload_message_id(payload)
        if message_id is not None:
            message_ids.append(message_id)

    messages_by_id: dict[int, Message] = {}
    if message_ids:
        for message in Message.objects.filter(
            simulation_id=simulation_id,
            id__in=message_ids,
        ).prefetch_related("media"):
            messages_by_id[message.id] = message

    items: list[EventEnvelope] = []
    for event in events:
        payload = dict(event.payload or {})
        if outbox_events.canonical_event_type(event.event_type) == outbox_events.MESSAGE_CREATED:
            message_id = payload_message_id(payload)
            message = messages_by_id.get(message_id) if message_id is not None else None
            if message is not None:
                payload.update(build_message_media_payload(message, request=request))
            else:
                payload.setdefault("media_list", [])

        items.append(
            EventEnvelope(
                event_id=str(event.id),
                event_type=event.event_type,
                created_at=event.created_at,
                correlation_id=event.correlation_id,
                payload=payload,
            )
        )

    logger.info(
        "chatlab.events.replay_listed",
        simulation_id=simulation_id,
        user_id=getattr(user, "id", None),
        last_event_id=last_event_id,
        returned=len(items),
        has_more=has_more,
        next_event_id=next_event_id,
    )

    return EventReplayResponse(
        items=items,
        next_event_id=next_event_id,
        has_more=has_more,
    )
