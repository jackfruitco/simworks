"""Message endpoints for API v1.

Provides CRUD operations for messages within simulations.
Uses cursor-based pagination for listing messages.
"""

from asgiref.sync import async_to_sync
from django.db import transaction
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.messages import (
    MessageCreate,
    MessageListResponse,
    MessageOut,
    message_to_out,
)
from api.v1.utils import get_simulation_for_user
from config.logging import get_logger
from apps.common.ratelimit import api_rate_limit, message_rate_limit

logger = get_logger(__name__)


def _resolve_conversation(sim, conversation_id=None):
    """Resolve the target conversation for a message.

    If ``conversation_id`` is given, fetch that specific conversation within the
    simulation. Otherwise fall back to the default patient conversation.
    """
    from apps.simcore.models import Conversation, ConversationType

    if conversation_id:
        try:
            return Conversation.objects.select_related(
                "conversation_type", "simulation"
            ).get(pk=conversation_id, simulation=sim)
        except Conversation.DoesNotExist:
            raise HttpError(404, "Conversation not found")

    # Default: patient conversation for this simulation.
    # Backward compatibility: create it on demand for older simulations that
    # were created before conversation auto-provisioning existed.
    patient_type = ConversationType.objects.filter(slug="simulated_patient").first()
    if not patient_type:
        raise HttpError(500, "Patient conversation type is not configured")

    conv, _ = Conversation.objects.get_or_create(
        simulation=sim,
        conversation_type=patient_type,
        defaults={
            "display_name": sim.sim_patient_display_name or patient_type.display_name,
            "display_initials": sim.sim_patient_initials or "Unk",
        },
    )
    return conv


def _enqueue_patient_reply(
    simulation_id: int, user_msg_pk: int, conversation_id: int | None = None,
) -> str | None:
    """Enqueue the GenerateReplyResponse service for a user message.

    Returns the call_id if successfully enqueued, None otherwise.
    """
    from apps.chatlab.orca.services import GenerateReplyResponse

    context = {
        "simulation_id": simulation_id,
        "user_msg": user_msg_pk,
    }
    if conversation_id:
        context["conversation_id"] = conversation_id

    async def _enqueue():
        return await GenerateReplyResponse.task.using(context=context).aenqueue()

    try:
        call_id = async_to_sync(_enqueue)()
        logger.info(
            "service.enqueued",
            service="GenerateReplyResponse",
            simulation_id=simulation_id,
            user_msg_pk=user_msg_pk,
            call_id=call_id,
        )
        return call_id
    except Exception as e:
        logger.exception(
            "service.enqueue_failed",
            service="GenerateReplyResponse",
            simulation_id=simulation_id,
            user_msg_pk=user_msg_pk,
            error=str(e),
        )
        return None


def _enqueue_stitch_reply(
    simulation_id: int, user_msg_pk: int, conversation_id: int,
) -> str | None:
    """Enqueue the GenerateStitchReply service for a user message.

    Returns the call_id if successfully enqueued, None otherwise.
    """
    from apps.chatlab.orca.services import GenerateStitchReply

    context = {
        "simulation_id": simulation_id,
        "user_msg": user_msg_pk,
        "conversation_id": conversation_id,
    }

    async def _enqueue():
        return await GenerateStitchReply.task.using(context=context).aenqueue()

    try:
        call_id = async_to_sync(_enqueue)()
        logger.info(
            "service.enqueued",
            service="GenerateStitchReply",
            simulation_id=simulation_id,
            user_msg_pk=user_msg_pk,
            conversation_id=conversation_id,
            call_id=call_id,
        )
        return call_id
    except Exception as e:
        logger.exception(
            "service.enqueue_failed",
            service="GenerateStitchReply",
            simulation_id=simulation_id,
            user_msg_pk=user_msg_pk,
            error=str(e),
        )
        return None


def _enqueue_ai_reply(conversation, simulation_id: int, user_msg_pk: int) -> str | None:
    """Dispatch to the correct AI service based on conversation type's ai_persona."""
    persona = conversation.conversation_type.ai_persona
    if persona == "patient":
        return _enqueue_patient_reply(simulation_id, user_msg_pk, conversation.id)
    elif persona == "stitch":
        return _enqueue_stitch_reply(simulation_id, user_msg_pk, conversation.id)
    else:
        logger.warning(
            "service.unknown_persona",
            persona=persona,
            conversation_id=conversation.id,
        )
        return None


router = Router(tags=["messages"], auth=DualAuth())


@router.get(
    "/{simulation_id}/messages/",
    response=MessageListResponse,
    summary="List messages in a simulation",
    description="Returns messages for a simulation with cursor-based pagination. "
    "Optionally filter by conversation_id.",
)
@api_rate_limit
def list_messages(
    request: HttpRequest,
    simulation_id: int,
    limit: int = Query(default=50, ge=1, le=100, description="Max messages to return"),
    cursor: str | None = Query(default=None, description="Cursor for pagination (message ID)"),
    order: str = Query(default="asc", description="Sort order: asc (oldest first) or desc (newest first)"),
    conversation_id: int | None = Query(default=None, description="Filter to a specific conversation"),
) -> MessageListResponse:
    """List messages in a simulation with cursor pagination."""
    from apps.chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    # Base queryset with select_related to avoid N+1 on conversation_type
    queryset = Message.objects.filter(simulation=sim, is_deleted=False).select_related(
        "conversation__conversation_type"
    )

    # Filter by conversation if specified
    if conversation_id is not None:
        queryset = queryset.filter(conversation_id=conversation_id)

    # Apply ordering using pk (stable, monotonic cursor)
    if order == "desc":
        queryset = queryset.order_by("-pk")
        if cursor:
            try:
                cursor_pk = int(cursor)
                queryset = queryset.filter(pk__lt=cursor_pk)
            except (ValueError, TypeError):
                raise HttpError(400, "Invalid cursor format")
    else:
        queryset = queryset.order_by("pk")
        if cursor:
            try:
                cursor_pk = int(cursor)
                queryset = queryset.filter(pk__gt=cursor_pk)
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
        next_cursor = str(last_message.pk)

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
    from apps.chatlab.models import Message, RoleChoices

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    # Resolve conversation and check per-conversation lock
    conversation = _resolve_conversation(sim, body.conversation_id)
    if conversation.is_locked:
        raise HttpError(400, "This conversation is locked")

    with transaction.atomic():
        # Create the user message
        message = Message.objects.create(
            simulation=sim,
            conversation=conversation,
            sender=user,
            content=body.content,
            role=RoleChoices.USER,
            message_type=body.message_type,
            is_from_ai=False,
            display_name=user.get_full_name() or user.email,
        )

        logger.info(
            "message.created",
            message_id=message.pk,
            simulation_id=simulation_id,
            conversation_id=conversation.pk,
            message_type=body.message_type,
        )

        # Enqueue the AI response generation (dispatched by conversation type)
        call_id = _enqueue_ai_reply(conversation, simulation_id, message.pk)
        if call_id is None:
            logger.warning(
                "message.ai_reply_not_enqueued",
                simulation_id=simulation_id,
                conversation_id=conversation.pk,
                message_id=message.pk,
                conversation_persona=conversation.conversation_type.ai_persona,
            )
            raise HttpError(400, "AI replies are not available for this conversation yet")

    # Return 202 Accepted since an AI response will be generated asynchronously
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
    from apps.chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    try:
        message = Message.objects.get(pk=message_id, simulation=sim, is_deleted=False)
    except Message.DoesNotExist:
        raise HttpError(404, "Message not found")

    return message_to_out(message)
