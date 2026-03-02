"""Conversation endpoints for API v1.

Provides list, create, and detail operations for conversations within simulations.
"""

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
from config.logging import get_logger
from apps.common.ratelimit import api_rate_limit

logger = get_logger(__name__)

router = Router(tags=["conversations"], auth=DualAuth())


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
    from apps.simcore.models import Conversation

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

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
    from apps.simcore.models import Conversation, ConversationType

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    # Resolve conversation type
    try:
        conv_type = ConversationType.objects.get(slug=body.conversation_type, is_active=True)
    except ConversationType.DoesNotExist:
        raise HttpError(400, f"Unknown conversation type: {body.conversation_type}")

    # Check if this conversation type already exists for this simulation
    existing = Conversation.objects.filter(
        simulation=sim, conversation_type=conv_type
    ).first()
    if existing:
        # Return the existing conversation (200, not 201 — nothing was created)
        return 200, conversation_to_out(existing)

    # Derive display name from conversation type
    if conv_type.ai_persona == "stitch":
        display_name = "Stitch"
        display_initials = "St"
    else:
        display_name = conv_type.display_name
        display_initials = conv_type.display_name[:2]

    conv = Conversation.objects.create(
        simulation=sim,
        conversation_type=conv_type,
        display_name=display_name,
        display_initials=display_initials,
    )

    logger.info(
        "conversation.created",
        conversation_id=conv.pk,
        simulation_id=simulation_id,
        conversation_type=body.conversation_type,
    )

    return 201, conversation_to_out(conv)


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
    from apps.simcore.models import Conversation

    user = request.auth
    sim = get_simulation_for_user(simulation_id, user)

    try:
        conv = (
            Conversation.objects.filter(simulation=sim)
            .select_related("conversation_type", "simulation")
            .get(uuid=conversation_uuid)
        )
    except Conversation.DoesNotExist:
        raise HttpError(404, "Conversation not found")

    return conversation_to_out(conv)
