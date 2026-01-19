"""Simulation endpoints for API v1.

Provides CRUD operations for simulations.
"""

import logging
from datetime import timedelta

from django.http import HttpRequest
from django.utils.timezone import now
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import JWTAuth
from api.v1.schemas.common import PaginatedResponse
from api.v1.schemas.simulations import (
    SimulationCreate,
    SimulationEndResponse,
    SimulationOut,
    simulation_to_out,
)
from core.ratelimit import api_rate_limit

logger = logging.getLogger(__name__)

router = Router(tags=["simulations"], auth=JWTAuth())


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
    status: str | None = Query(default=None, description="Filter by status: in_progress, completed"),
) -> PaginatedResponse[SimulationOut]:
    """List all simulations for the authenticated user."""
    from simulation.models import Simulation

    user = request.auth
    queryset = Simulation.objects.filter(user=user).order_by("-start_timestamp")

    # Apply status filter
    if status == "in_progress":
        queryset = queryset.filter(end_timestamp__isnull=True)
    elif status == "completed":
        queryset = queryset.filter(end_timestamp__isnull=False)

    # Apply cursor-based pagination (using ID for simplicity)
    if cursor:
        try:
            cursor_id = int(cursor)
            queryset = queryset.filter(pk__lt=cursor_id)
        except (ValueError, TypeError):
            raise HttpError(400, "Invalid cursor format")

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


@router.get(
    "/{simulation_id}/",
    response=SimulationOut,
    summary="Get simulation details",
    description="Returns details for a specific simulation.",
)
@api_rate_limit
def get_simulation(request: HttpRequest, simulation_id: int) -> SimulationOut:
    """Get a specific simulation by ID."""
    from simulation.models import Simulation

    user = request.auth

    try:
        sim = Simulation.objects.get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found")

    return simulation_to_out(sim)


@router.post(
    "/",
    response={201: SimulationOut},
    summary="Create a new simulation",
    description="Creates a new simulation for the authenticated user.",
)
@api_rate_limit
def create_simulation(request: HttpRequest, body: SimulationCreate) -> SimulationOut:
    """Create a new simulation."""
    from simulation.models import Simulation

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

    logger.info("Created simulation %d for user %s", sim.pk, user.username)
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
    from simulation.models import Simulation

    user = request.auth

    try:
        sim = Simulation.objects.get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist:
        raise HttpError(404, "Simulation not found")

    if sim.is_complete:
        raise HttpError(400, "Simulation is already ended")

    # End the simulation (this also triggers feedback generation)
    sim.end()

    logger.info("Ended simulation %d for user %s", sim.pk, user.username)

    return SimulationEndResponse(
        id=sim.pk,
        end_timestamp=sim.end_timestamp,
        status="completed",
    )
