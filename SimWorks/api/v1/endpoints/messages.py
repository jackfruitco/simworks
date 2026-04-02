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
from apps.chatlab.access import require_lab_access as require_chatlab_access
from apps.common.outbox import event_types as outbox_events
from apps.common.ratelimit import api_rate_limit, message_rate_limit
from apps.common.retries import has_user_retries_remaining
from config.logging import get_logger

logger = get_logger(__name__)


def _pii_scan_result(content: str) -> dict:
    from apps.privacy import policies
    from apps.privacy.services.classification import scan_text_for_pii

    if not policies.basic_pii_scan_enabled():
        return {"has_pii": False, "matches": {}}
    return scan_text_for_pii(content)


def _emit_message_status(
    *,
    simulation_id: int,
    message_id: int,
    status: str,
    retryable: bool | None = None,
    error_code: str | None = None,
    error_text: str | None = None,
) -> None:
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    payload = {
        "id": message_id,
        "status": status,
        "retryable": retryable,
        "error_code": error_code,
        "error_text": error_text,
    }
    event = enqueue_event_sync(
        event_type=outbox_events.MESSAGE_DELIVERY_UPDATED,
        simulation_id=simulation_id,
        payload=payload,
        idempotency_key=(
            f"{outbox_events.MESSAGE_DELIVERY_UPDATED}:"
            f"{message_id}:{status}:{retryable}:{error_code or 'none'}"
        ),
    )
    if event:
        poke_drain_sync()


def _mark_message_failed(
    message_id: int, error_code: str, error_text: str, retryable: bool = True
) -> None:
    from apps.chatlab.models import Message

    try:
        msg = Message.objects.get(pk=message_id)
    except Message.DoesNotExist:
        return

    msg.delivery_status = Message.DeliveryStatus.FAILED
    msg.delivery_error_code = error_code
    msg.delivery_error_text = error_text
    msg.delivery_retryable = retryable and has_user_retries_remaining(msg.delivery_retry_count)
    msg.save(
        update_fields=[
            "delivery_status",
            "delivery_error_code",
            "delivery_error_text",
            "delivery_retryable",
        ]
    )
    _emit_message_status(
        simulation_id=msg.simulation_id,
        message_id=msg.id,
        status=Message.DeliveryStatus.FAILED,
        retryable=msg.delivery_retryable,
        error_code=msg.delivery_error_code,
        error_text=msg.delivery_error_text,
    )


def _resolve_conversation(sim, conversation_id=None):
    """Resolve the target conversation for a message.

    If ``conversation_id`` is given, fetch that specific conversation within the
    simulation. Otherwise fall back to the default patient conversation.
    """
    from apps.simcore.models import Conversation, ConversationType

    if conversation_id:
        try:
            return Conversation.objects.select_related("conversation_type", "simulation").get(
                pk=conversation_id, simulation=sim
            )
        except Conversation.DoesNotExist as err:
            raise HttpError(404, "Conversation not found") from err

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
    simulation_id: int,
    user_msg_pk: int,
    conversation_id: int | None = None,
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
    simulation_id: int,
    user_msg_pk: int,
    conversation_id: int,
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


def _supports_ai_reply(conversation) -> bool:
    """Return whether this conversation can enqueue AI replies."""
    return conversation.conversation_type.ai_persona in {"patient", "stitch"}


def _enqueue_ai_reply_and_handle_failure(
    conversation,
    simulation_id: int,
    user_msg_pk: int,
) -> None:
    call_id = _enqueue_ai_reply(conversation, simulation_id, user_msg_pk)
    if call_id:
        from apps.chatlab.models import Message

        try:
            message = Message.objects.get(pk=user_msg_pk)
        except Message.DoesNotExist:
            return
        _emit_message_status(
            simulation_id=simulation_id,
            message_id=user_msg_pk,
            status=Message.DeliveryStatus.SENT,
            retryable=message.delivery_retryable,
        )
        return
    _mark_message_failed(
        message_id=user_msg_pk,
        error_code="enqueue_failed",
        error_text="Message queued locally but failed to start AI processing. Try again.",
        retryable=True,
    )


router = Router(tags=["messages"], auth=DualAuth())


def _require_chatlab_access(request: HttpRequest):
    return require_chatlab_access(request.auth, request=request)


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
    order: str = Query(
        default="asc", description="Sort order: asc (oldest first) or desc (newest first)"
    ),
    conversation_id: int | None = Query(
        default=None, description="Filter to a specific conversation"
    ),
) -> MessageListResponse:
    """List messages in a simulation with cursor pagination."""
    _require_chatlab_access(request)
    from apps.chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    # Base queryset with select_related to avoid N+1 on conversation_type
    queryset = (
        Message.objects.filter(simulation=sim, is_deleted=False)
        .select_related("conversation__conversation_type")
        .prefetch_related("media")
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
            except (ValueError, TypeError) as err:
                raise HttpError(400, "Invalid cursor format") from err
    else:
        queryset = queryset.order_by("pk")
        if cursor:
            try:
                cursor_pk = int(cursor)
                queryset = queryset.filter(pk__gt=cursor_pk)
            except (ValueError, TypeError) as err:
                raise HttpError(400, "Invalid cursor format") from err

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
        items=[message_to_out(msg, request=request) for msg in messages],
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
    _require_chatlab_access(request)
    from apps.chatlab.models import Message, RoleChoices

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    # ── Guard: ChatLab send-lock check ──────────────────────────────
    _guard_chat_send(sim)

    # Resolve conversation and check per-conversation lock
    conversation = _resolve_conversation(sim, body.conversation_id)
    if conversation.is_locked:
        raise HttpError(400, "This conversation is locked")
    if not _supports_ai_reply(conversation):
        logger.warning(
            "message.ai_reply_not_enqueued",
            simulation_id=simulation_id,
            conversation_id=conversation.pk,
            conversation_persona=conversation.conversation_type.ai_persona,
        )
        raise HttpError(400, "AI replies are not available for this conversation yet")

    with transaction.atomic():
        pii_scan = _pii_scan_result(body.content)
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
        message.delivery_status = Message.DeliveryStatus.SENT
        message.delivery_retryable = True
        message.save(update_fields=["delivery_status", "delivery_retryable"])

        logger.info(
            "message.created",
            message_id=message.pk,
            simulation_id=simulation_id,
            conversation_id=conversation.pk,
            message_type=body.message_type,
            pii_flagged=pii_scan["has_pii"],
        )

        # Enqueue only after the user message transaction commits.
        transaction.on_commit(
            lambda: _enqueue_ai_reply_and_handle_failure(conversation, simulation_id, message.pk)
        )

    # Return 202 Accepted since an AI response will be generated asynchronously
    message.refresh_from_db()
    return 202, message_to_out(message, request=request)


@router.post(
    "/{simulation_id}/messages/{message_id}/retry/",
    response={202: MessageOut},
    summary="Retry a failed outgoing message",
    description="Retries AI processing for a previously failed outgoing user message.",
)
@message_rate_limit
def retry_message(
    request: HttpRequest,
    simulation_id: int,
    message_id: int,
) -> tuple[int, MessageOut]:
    _require_chatlab_access(request)
    from apps.chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    # ── Guard: ChatLab send-lock check ──────────────────────────────
    _guard_chat_send(sim)

    try:
        message = Message.objects.select_related("conversation__conversation_type").get(
            pk=message_id,
            simulation=sim,
            sender=user,
            is_deleted=False,
            is_from_ai=False,
        )
    except Message.DoesNotExist as err:
        raise HttpError(404, "Message not found") from err

    if message.delivery_status != Message.DeliveryStatus.FAILED:
        raise HttpError(400, "Only failed messages can be retried")

    if not message.delivery_retryable or not has_user_retries_remaining(
        message.delivery_retry_count
    ):
        raise HttpError(400, "Retry limit reached for this message")

    conversation = message.conversation
    if conversation.is_locked:
        raise HttpError(400, "This conversation is locked")
    if not _supports_ai_reply(conversation):
        raise HttpError(400, "AI replies are not available for this conversation")

    with transaction.atomic():
        message.delivery_retry_count += 1
        message.delivery_status = Message.DeliveryStatus.SENT
        message.delivery_error_code = ""
        message.delivery_error_text = ""
        message.delivery_retryable = has_user_retries_remaining(message.delivery_retry_count)
        message.save(
            update_fields=[
                "delivery_retry_count",
                "delivery_status",
                "delivery_error_code",
                "delivery_error_text",
                "delivery_retryable",
            ]
        )

        transaction.on_commit(
            lambda: _enqueue_ai_reply_and_handle_failure(conversation, simulation_id, message.pk)
        )

    message.refresh_from_db()
    return 202, message_to_out(message, request=request)


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
    _require_chatlab_access(request)
    from apps.chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    try:
        message = (
            Message.objects.select_related("conversation__conversation_type")
            .prefetch_related("media")
            .get(pk=message_id, simulation=sim, is_deleted=False)
        )
    except Message.DoesNotExist as err:
        raise HttpError(404, "Message not found") from err

    return message_to_out(message, request=request)


@router.patch(
    "/{simulation_id}/messages/{message_id}/read/",
    response=MessageOut,
    summary="Mark a message as read",
    description="Marks a message as read by the current user.",
)
@api_rate_limit
def mark_message_read(
    request: HttpRequest,
    simulation_id: int,
    message_id: int,
) -> MessageOut:
    """Mark a message as read."""
    _require_chatlab_access(request)
    from apps.chatlab.models import Message

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    try:
        message = (
            Message.objects.select_related("conversation__conversation_type")
            .prefetch_related("media")
            .get(pk=message_id, simulation=sim, is_deleted=False)
        )
    except Message.DoesNotExist as err:
        raise HttpError(404, "Message not found") from err

    if not message.is_read:
        message.is_read = True
        message.save(update_fields=["is_read"])

    return message_to_out(message, request=request)


# ── Guard helper ──────────────────────────────────────────────────────


def _guard_chat_send(sim) -> None:
    """Check ChatLab send-lock and raise ``GuardDeniedError`` if denied.

    Uses ``denial_for_state()`` when a ``SessionPresence`` exists so the
    403 response carries the same canonical code, resumable/terminal
    semantics, and metadata as the guard-state endpoint.
    """
    from api.v1.errors import GuardDeniedError
    from apps.guards.models import SessionPresence
    from apps.guards.presentation import denial_for_state, denial_from_reason
    from apps.guards.services import check_chat_send_allowed

    decision = check_chat_send_allowed(sim.pk)
    if not decision.allowed:
        # Try state-aware signal first for canonical semantics.
        signal = None
        try:
            presence = SessionPresence.objects.get(simulation_id=sim.pk)
            signal = denial_for_state(presence.guard_state, presence.pause_reason)
        except SessionPresence.DoesNotExist:
            pass

        if signal is None:
            # Non-state denial (e.g. budget exhaustion before state transition).
            signal = denial_from_reason(
                decision.denial_reason,
                decision.denial_message,
            )
        raise GuardDeniedError(signal)
