"""Message endpoints for API v1.

Provides CRUD operations for messages within simulations.
Uses cursor-based pagination for listing messages.
"""

from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import JWTAuth
from api.v1.schemas.messages import (
    MessageCreate,
    MessageListResponse,
    MessageOut,
    message_to_out,
)
from config.logging import get_logger
from core.ratelimit import api_rate_limit, message_rate_limit

logger = get_logger(__name__)

router = Router(tags=["messages"], auth=JWTAuth())


def get_simulation_for_user(simulation_id: int, user):
    """Get a simulation, ensuring the user has access."""
    from simulation.models import Simulation

    try:
        return Simulation.objects.get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found")


@router.get(
    "/{simulation_id}/messages/",
    response=MessageListResponse,
    summary="List messages in a simulation",
    description="Returns messages for a simulation with cursor-based pagination.",
)
@api_rate_limit
def list_messages(
    request: HttpRequest,
    simulation_id: int,
    limit: int = Query(default=50, ge=1, le=100, description="Max messages to return"),
    cursor: str | None = Query(default=None, description="Cursor for pagination (message ID)"),
    order: str = Query(default="asc", description="Sort order: asc (oldest first) or desc (newest first)"),
) -> MessageListResponse:
    """List messages in a simulation with cursor pagination."""
    from chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    # Base queryset
    queryset = Message.objects.filter(simulation=sim, is_deleted=False)

    # Apply ordering
    if order == "desc":
        queryset = queryset.order_by("-order")
        # Cursor is for messages with order < cursor
        if cursor:
            try:
                cursor_order = int(cursor)
                queryset = queryset.filter(order__lt=cursor_order)
            except (ValueError, TypeError):
                raise HttpError(400, "Invalid cursor format")
    else:
        queryset = queryset.order_by("order")
        # Cursor is for messages with order > cursor
        if cursor:
            try:
                cursor_order = int(cursor)
                queryset = queryset.filter(order__gt=cursor_order)
            except (ValueError, TypeError):
                raise HttpError(400, "Invalid cursor format")

    # Fetch one extra to check for more
    messages = list(queryset[: limit + 1])
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    # Determine next cursor
    next_cursor = None
    if has_more and messages:
        last_message = messages[-1]
        next_cursor = str(last_message.order)

    return MessageListResponse(
        items=[message_to_out(msg) for msg in messages],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/{simulation_id}/messages/",
    response={201: MessageOut, 202: MessageOut},
    summary="Create a message",
    description="Creates a new message in a simulation. Returns 201 for immediate response, 202 if AI response is pending.",
)
@message_rate_limit
def create_message(
    request: HttpRequest,
    simulation_id: int,
    body: MessageCreate,
) -> tuple[int, MessageOut]:
    """Create a new message in a simulation.

    This creates a user message and may trigger an AI response.
    Returns 201 if the message was created successfully, or
    202 if the message was created and an AI response is pending.
    """
    from chatlab.models import Message, RoleChoices

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    # Check if simulation is still in progress
    if sim.is_complete:
        raise HttpError(400, "Cannot send messages to a completed simulation")

    # Create the user message
    message = Message.objects.create(
        simulation=sim,
        sender=user,
        content=body.content,
        role=RoleChoices.USER,
        message_type=body.message_type,
        is_from_ai=False,
        display_name=user.get_full_name() or user.username,
    )

    logger.info(
        "message.created",
        message_id=message.pk,
        simulation_id=simulation_id,
        message_type=body.message_type,
    )

    # Return 202 Accepted since an AI response will be generated asynchronously
    # The actual AI response triggering would be handled by the service layer
    return 202, message_to_out(message)


@router.get(
    "/{simulation_id}/messages/{message_id}/",
    response=MessageOut,
    summary="Get a specific message",
    description="Returns a specific message by ID.",
)
@api_rate_limit
def get_message(
    request: HttpRequest,
    simulation_id: int,
    message_id: int,
) -> MessageOut:
    """Get a specific message by ID."""
    from chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    try:
        message = Message.objects.get(pk=message_id, simulation=sim, is_deleted=False)
    except Message.DoesNotExist:
        raise HttpError(404, "Message not found")

    return message_to_out(message)
