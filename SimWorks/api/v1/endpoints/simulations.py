"""Simulation endpoints for API v1.

Provides CRUD operations for simulations.
"""

from datetime import timedelta

from asgiref.sync import async_to_sync
from django.db.models import Q
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.common import PaginatedResponse
from api.v1.schemas.simulations import (
    SimulationCreate,
    SimulationEndResponse,
    SimulationOut,
    SimulationQuickCreate,
    simulation_to_out,
)
from apps.common.ratelimit import api_rate_limit
from apps.common.retries import (
    has_user_retries_remaining,
    is_simulation_initial_generation_retryable,
)
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["simulations"], auth=DualAuth())


def _emit_feedback_event(simulation_id: int, event_type: str, payload: dict) -> None:
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    event = enqueue_event_sync(
        event_type=event_type,
        simulation_id=simulation_id,
        payload=payload,
    )
    if event:
        poke_drain_sync()


def _enqueue_initial_response(simulation, conversation_id: int) -> str | None:
    from apps.chatlab.orca.services import GenerateInitialResponse

    async def _enqueue():
        return await GenerateInitialResponse.task.using(
            context={
                "simulation_id": simulation.id,
                "user_id": simulation.user_id,
                "conversation_id": conversation_id,
            }
        ).aenqueue()

    try:
        return async_to_sync(_enqueue)()
    except Exception:
        logger.exception(
            "service.enqueue_failed",
            service="GenerateInitialResponse",
            simulation_id=simulation.id,
        )
        return None


def _enqueue_feedback(simulation_id: int) -> str | None:
    from apps.simcore.orca.services import GenerateInitialFeedback

    async def _enqueue():
        return await GenerateInitialFeedback.task.using(
            context={"simulation_id": simulation_id}
        ).aenqueue()

    try:
        return async_to_sync(_enqueue)()
    except Exception:
        logger.exception(
            "service.enqueue_failed",
            service="GenerateInitialFeedback",
            simulation_id=simulation_id,
        )
        return None


@router.get(
    "/",
    response=PaginatedResponse[SimulationOut],
    summary="List user's simulations",
    description="Returns all simulations for the authenticated user, ordered by most recent first.",
)
@api_rate_limit
def list_simulations(
    request: HttpRequest,
    limit: int = Query(default=20, ge=1, le=100, description="Max items to return"),
    cursor: str | None = Query(default=None, description="Cursor for pagination (simulation ID)"),
    status: str | None = Query(
        default=None,
        description="Filter by status: in_progress, completed, timed_out, failed, canceled",
    ),
    q: str | None = Query(default=None, description="Search query"),
    search_messages: bool = Query(
        default=False,
        description="When true, include chat message content in search",
    ),
) -> PaginatedResponse[SimulationOut]:
    """List all simulations for the authenticated user."""
    from apps.simcore.models import Simulation

    user = request.auth
    queryset = (
        Simulation.objects.filter(user=user)
        .select_related("chatlab_session")
        .order_by("-start_timestamp", "-pk")
    )

    # Apply status filter
    if status == "in_progress":
        queryset = queryset.filter(status="in_progress", end_timestamp__isnull=True)
    elif status == "completed":
        queryset = queryset.filter(
            Q(status="completed") | Q(status="in_progress", end_timestamp__isnull=False)
        )
    elif status in {"failed", "canceled"}:
        queryset = queryset.filter(status=status)
    elif status == "timed_out":
        queryset = queryset.filter(status="timed_out")

    search = (q or "").strip()
    if search:
        search_filter = (
            Q(diagnosis__icontains=search)
            | Q(chief_complaint__icontains=search)
            | Q(prompt_instruction__icontains=search)
            | Q(prompt_message__icontains=search)
        )
        if search_messages:
            search_filter |= Q(input__content__icontains=search)
        queryset = queryset.filter(search_filter).distinct()

    # Apply cursor-based pagination (using ID for simplicity)
    if cursor:
        try:
            cursor_id = int(cursor)
        except (ValueError, TypeError):
            raise HttpError(400, "Invalid cursor format") from None

        cursor_simulation = queryset.filter(pk=cursor_id).first()
        if cursor_simulation is None:
            raise HttpError(400, "Invalid cursor") from None

        queryset = queryset.filter(
            Q(start_timestamp__lt=cursor_simulation.start_timestamp)
            | Q(
                start_timestamp=cursor_simulation.start_timestamp,
                pk__lt=cursor_simulation.pk,
            )
        )

    simulations = list(queryset[: limit + 1])
    has_more = len(simulations) > limit
    if has_more:
        simulations = simulations[:limit]

    # Calculate next cursor (ID of the last item)
    next_cursor = str(simulations[-1].pk) if has_more and simulations else None

    return PaginatedResponse(
        items=[simulation_to_out(sim) for sim in simulations],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/",
    response={201: SimulationOut},
    summary="Create a new simulation",
    description="Creates a new simulation for the authenticated user.",
)
@api_rate_limit
def create_simulation(request: HttpRequest, body: SimulationCreate) -> SimulationOut:
    """Create a new simulation."""
    from apps.simcore.models import Simulation

    user = request.auth

    time_limit = None
    if body.time_limit_seconds:
        time_limit = timedelta(seconds=body.time_limit_seconds)

    sim = Simulation.objects.create(
        user=user,
        diagnosis=body.diagnosis,
        chief_complaint=body.chief_complaint,
        sim_patient_full_name=body.patient_full_name,
        time_limit=time_limit,
    )

    logger.info(
        "simulation.created",
        simulation_id=sim.pk,
        diagnosis=body.diagnosis,
        patient_name=body.patient_full_name,
    )
    return simulation_to_out(sim)


@router.post(
    "/quick-create/",
    response={201: SimulationOut},
    summary="Quick-create ChatLab simulation",
    description=(
        "Creates a ChatLab simulation with server-generated patient identity and "
        "optional modifiers, and enqueues initial response generation."
    ),
)
@api_rate_limit
def quick_create_simulation(
    request: HttpRequest,
    body: SimulationQuickCreate,
) -> tuple[int, SimulationOut]:
    from apps.chatlab.utils import create_new_simulation

    user = request.auth
    simulation = async_to_sync(create_new_simulation)(
        user=user,
        modifiers=body.modifiers,
    )
    return 201, simulation_to_out(simulation)


@router.get(
    "/{simulation_id}/",
    response=SimulationOut,
    summary="Get simulation details",
    description="Returns details for a specific simulation.",
)
@api_rate_limit
def get_simulation(request: HttpRequest, simulation_id: int) -> SimulationOut:
    """Get a specific simulation by ID."""
    from apps.simcore.models import Simulation

    user = request.auth

    try:
        sim = (
            Simulation.objects.select_related("chatlab_session").get(
                pk=simulation_id, user=user
            )
        )
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found") from None

    return simulation_to_out(sim)


@router.post(
    "/{simulation_id}/end/",
    response=SimulationEndResponse,
    summary="End a simulation",
    description="Ends an in-progress simulation and triggers feedback generation.",
)
@api_rate_limit
def end_simulation(request: HttpRequest, simulation_id: int) -> SimulationEndResponse:
    """End a simulation."""
    from apps.simcore.models import Simulation

    user = request.auth

    try:
        sim = Simulation.objects.get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found") from None

    if sim.is_complete:
        raise HttpError(400, "Simulation is already ended")

    # End the simulation (this also triggers feedback generation)
    sim.end()

    logger.info("simulation.ended", simulation_id=sim.pk)

    return SimulationEndResponse(
        id=sim.pk,
        end_timestamp=sim.end_timestamp,
        status="completed",
    )


@router.post(
    "/{simulation_id}/retry-initial/",
    response={202: SimulationOut},
    summary="Retry initial simulation generation",
    description="Retries initial patient generation for a failed simulation.",
)
@api_rate_limit
def retry_initial(request: HttpRequest, simulation_id: int) -> tuple[int, SimulationOut]:
    from apps.simcore.models import Conversation, ConversationType, Simulation

    user = request.auth
    try:
        sim = Simulation.objects.select_related("chatlab_session").get(
            pk=simulation_id, user=user
        )
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found") from None

    try:
        sim.chatlab_session
    except Exception:
        raise HttpError(400, "Initial generation retry is only available for ChatLab simulations")

    if sim.status != Simulation.SimulationStatus.FAILED:
        raise HttpError(400, "Simulation is not in failed state")

    if not is_simulation_initial_generation_retryable(sim):
        raise HttpError(400, "Initial generation retry is not available for this failure")

    if not has_user_retries_remaining(sim.initial_retry_count):
        raise HttpError(400, "Retry limit reached for initial generation")

    patient_type = ConversationType.objects.filter(slug="simulated_patient").first()
    if not patient_type:
        raise HttpError(500, "Patient conversation type is not configured")

    conversation, _ = Conversation.objects.get_or_create(
        simulation=sim,
        conversation_type=patient_type,
        defaults={
            "display_name": sim.sim_patient_display_name or patient_type.display_name,
            "display_initials": sim.sim_patient_initials or "Unk",
        },
    )

    sim.initial_retry_count += 1
    sim.save(update_fields=["initial_retry_count"])
    sim.mark_in_progress()

    call_id = _enqueue_initial_response(sim, conversation.id)
    if not call_id:
        retryable = has_user_retries_remaining(sim.initial_retry_count)
        sim.mark_failed(
            reason_code="chatlab_initial_generation_enqueue_failed",
            reason_text="We could not restart this simulation. Please try again.",
            retryable=retryable,
        )
        raise HttpError(500, "Failed to enqueue initial generation retry")

    return 202, simulation_to_out(sim)


@router.post(
    "/{simulation_id}/retry-feedback/",
    response={202: SimulationOut},
    summary="Retry feedback generation",
    description="Retries post-simulation feedback generation.",
)
@api_rate_limit
def retry_feedback(request: HttpRequest, simulation_id: int) -> tuple[int, SimulationOut]:
    from apps.simcore.models import Simulation

    user = request.auth
    try:
        sim = Simulation.objects.get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found") from None

    if sim.status not in {
        Simulation.SimulationStatus.COMPLETED,
        Simulation.SimulationStatus.TIMED_OUT,
    }:
        raise HttpError(400, "Feedback retry is only available for ended simulations")

    if not has_user_retries_remaining(sim.feedback_retry_count):
        raise HttpError(400, "Retry limit reached for feedback generation")

    sim.feedback_retry_count += 1
    sim.save(update_fields=["feedback_retry_count"])

    _emit_feedback_event(
        simulation_id=sim.id,
        event_type="feedback.retrying",
        payload={
            "simulation_id": sim.id,
            "retryable": has_user_retries_remaining(sim.feedback_retry_count),
            "retry_count": sim.feedback_retry_count,
        },
    )

    call_id = _enqueue_feedback(sim.id)
    if not call_id:
        retryable = has_user_retries_remaining(sim.feedback_retry_count)
        _emit_feedback_event(
            simulation_id=sim.id,
            event_type="feedback.failed",
            payload={
                "simulation_id": sim.id,
                "error_code": "feedback_enqueue_failed",
                "error_text": "Feedback generation failed. Please try again.",
                "retryable": retryable,
                "retry_count": sim.feedback_retry_count,
            },
        )
        raise HttpError(500, "Failed to enqueue feedback retry")

    return 202, simulation_to_out(sim)
