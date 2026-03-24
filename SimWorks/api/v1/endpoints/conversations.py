"""Conversation endpoints for API v1.

Provides list, create, and detail operations for conversations within simulations.
"""

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.conversations import (
    ConversationCreate,
    ConversationListResponse,
    ConversationOut,
    conversation_to_out,
)
from api.v1.utils import get_simulation_for_user
from apps.chatlab.access import require_lab_access as require_chatlab_access
from apps.common.outbox import event_types as outbox_events
from apps.common.ratelimit import api_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["conversations"], auth=DualAuth())


def _require_chatlab_access(request: HttpRequest):
    return require_chatlab_access(request.auth, request=request)


STITCH_GREETING_MESSAGE = (
    "Hey, what would you like to discuss? Do you have a specific question "
    "about your performance or this scenario?"
)


def _create_feedback_starter_message(sim, conversation):
    """Create the initial Stitch greeting message for new feedback conversations."""
    from apps.chatlab.media_payloads import build_chat_message_event_payload
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync
    from apps.common.utils.accounts import get_system_user

    stitch_user = get_system_user("Stitch")
    message = Message.objects.create(
        simulation=sim,
        conversation=conversation,
        sender=stitch_user,
        content=STITCH_GREETING_MESSAGE,
        role=RoleChoices.ASSISTANT,
        message_type=Message.MessageType.TEXT,
        is_from_ai=True,
        display_name="Stitch",
    )

    payload = build_chat_message_event_payload(
        message,
        conversation_type=conversation.conversation_type.slug,
        status="completed",
    )
    event = enqueue_event_sync(
        event_type=outbox_events.MESSAGE_CREATED,
        simulation_id=sim.id,
        payload=payload,
        idempotency_key=f"{outbox_events.MESSAGE_CREATED}:{message.id}",
    )
    if event:
        poke_drain_sync()


@router.get(
    "/{simulation_id}/conversations/",
    response=ConversationListResponse,
    summary="List conversations in a simulation",
    description="Returns all conversations for a simulation, ordered by creation time.",
)
@api_rate_limit
def list_conversations(
    request: HttpRequest,
    simulation_id: int,
) -> ConversationListResponse:
    """List conversations in a simulation."""
    _require_chatlab_access(request)
    from apps.simcore.models import Conversation

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    conversations = (
        Conversation.objects.filter(simulation=sim, is_archived=False)
        .select_related("conversation_type", "simulation")
        .order_by("created_at")
    )

    return ConversationListResponse(
        items=[conversation_to_out(c) for c in conversations],
    )


@router.post(
    "/{simulation_id}/conversations/",
    response={200: ConversationOut, 201: ConversationOut},
    summary="Create a conversation",
    description="Creates a new conversation in a simulation (e.g. start a Stitch feedback chat).",
)
@api_rate_limit
def create_conversation(
    request: HttpRequest,
    simulation_id: int,
    body: ConversationCreate,
) -> tuple[int, ConversationOut]:
    """Create a new conversation in a simulation."""
    _require_chatlab_access(request)
    from apps.simcore.models import Conversation, ConversationType

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    # Resolve conversation type
    try:
        conv_type = ConversationType.objects.get(slug=body.conversation_type, is_active=True)
    except ConversationType.DoesNotExist as err:
        raise HttpError(400, f"Unknown conversation type: {body.conversation_type}") from err

    # Derive display name from conversation type
    if conv_type.ai_persona == "stitch":
        display_name = "Stitch"
        display_initials = "St"
    else:
        display_name = conv_type.display_name
        display_initials = conv_type.display_name[:2]

    try:
        with transaction.atomic():
            conv, created = Conversation.objects.get_or_create(
                simulation=sim,
                conversation_type=conv_type,
                defaults={
                    "display_name": display_name,
                    "display_initials": display_initials,
                },
            )
            if created and conv_type.slug == "simulated_feedback":
                _create_feedback_starter_message(sim, conv)
    except IntegrityError:
        conv = Conversation.objects.get(simulation=sim, conversation_type=conv_type)
        created = False

    logger.info(
        "conversation.created",
        conversation_id=conv.pk,
        simulation_id=simulation_id,
        conversation_type=body.conversation_type,
    )

    status_code = 201 if created else 200
    return status_code, conversation_to_out(conv)


@router.get(
    "/{simulation_id}/conversations/{conversation_uuid}/",
    response=ConversationOut,
    summary="Get a specific conversation",
    description="Returns a specific conversation by UUID.",
)
@api_rate_limit
def get_conversation(
    request: HttpRequest,
    simulation_id: int,
    conversation_uuid: str,
) -> ConversationOut:
    """Get a specific conversation by UUID."""
    _require_chatlab_access(request)
    from apps.simcore.models import Conversation

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    try:
        conv = (
            Conversation.objects.filter(simulation=sim)
            .select_related("conversation_type", "simulation")
            .get(uuid=conversation_uuid)
        )
    except Conversation.DoesNotExist as err:
        raise HttpError(404, "Conversation not found") from err

    return conversation_to_out(conv)
