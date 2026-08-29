"""VoiceLab endpoints for ChatLab-backed simulations."""

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.voice import VoiceSessionCreate, VoiceSessionOut, voice_session_to_out
from api.v1.utils import get_chatlab_simulation_for_user
from apps.chatlab.access import require_lab_access as require_chatlab_access
from apps.chatlab.voice import create_voice_session, end_voice_session
from apps.common.ratelimit import api_rate_limit
from apps.simcore.models import Simulation

router = Router(tags=["voice"], auth=DualAuth())


def _require_chatlab_access(request: HttpRequest):
    return require_chatlab_access(request.auth, request=request)


def _resolve_conversation(sim, conversation_id=None):
    from apps.simcore.models import Conversation, ConversationType

    if conversation_id:
        try:
            return Conversation.objects.select_related("conversation_type", "simulation").get(
                pk=conversation_id, simulation=sim
            )
        except Conversation.DoesNotExist as err:
            raise HttpError(404, "Conversation not found") from err

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


def _guard_voice_session_start(sim: Simulation) -> None:
    from api.v1.errors import GuardDeniedError
    from apps.guards.models import SessionPresence
    from apps.guards.presentation import denial_for_state, denial_from_reason
    from apps.guards.services import check_chat_send_allowed

    if sim.status != Simulation.SimulationStatus.IN_PROGRESS:
        raise HttpError(400, "Voice sessions can only be started for in-progress simulations")

    decision = check_chat_send_allowed(sim.pk)
    if not decision.allowed:
        signal = None
        try:
            presence = SessionPresence.objects.get(simulation_id=sim.pk)
            signal = denial_for_state(presence.guard_state, presence.pause_reason)
        except SessionPresence.DoesNotExist:
            pass

        if signal is None:
            signal = denial_from_reason(decision.denial_reason, decision.denial_message)
        raise GuardDeniedError(signal)


@router.post(
    "/{simulation_id}/voice/session/",
    response={201: VoiceSessionOut},
    summary="Start a VoiceLab session",
    description=(
        "Creates a provider-backed live voice session for an in-progress ChatLab "
        "simulation and returns ephemeral connection material for iOS."
    ),
)
@api_rate_limit
def start_voice_session(
    request: HttpRequest,
    simulation_id: int,
    body: VoiceSessionCreate,
) -> tuple[int, VoiceSessionOut]:
    _require_chatlab_access(request)
    user = request.auth
    sim = get_chatlab_simulation_for_user(simulation_id, user, request=request)
    _guard_voice_session_start(sim)
    conversation = _resolve_conversation(sim, body.conversation_id)

    voice_session, start = create_voice_session(
        user=user,
        simulation=sim,
        conversation=conversation,
        transport=body.transport,
        model=body.model,
        voice=body.voice,
        client_metadata=body.client_metadata,
        correlation_id=getattr(request, "correlation_id", None),
    )
    return 201, voice_session_to_out(voice_session, start=start)


@router.post(
    "/{simulation_id}/voice/sessions/{voice_session_uuid}/end/",
    response=VoiceSessionOut,
    summary="End a VoiceLab session",
    description="Marks a VoiceLab session ended and emits a durable lifecycle event.",
)
@api_rate_limit
def end_voice_session_endpoint(
    request: HttpRequest,
    simulation_id: int,
    voice_session_uuid: str,
) -> VoiceSessionOut:
    _require_chatlab_access(request)
    user = request.auth
    sim = get_chatlab_simulation_for_user(simulation_id, user, request=request)

    from apps.chatlab.models import VoiceSession

    try:
        voice_session = VoiceSession.objects.get(
            uuid=voice_session_uuid,
            simulation=sim,
            created_by=user,
        )
    except VoiceSession.DoesNotExist as err:
        raise HttpError(404, "Voice session not found") from err

    voice_session = end_voice_session(
        voice_session=voice_session,
        correlation_id=getattr(request, "correlation_id", None),
    )
    return voice_session_to_out(voice_session)
