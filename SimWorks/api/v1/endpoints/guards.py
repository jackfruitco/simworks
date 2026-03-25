"""Guard framework API endpoints.

Provides heartbeat and guard-state retrieval for clients.
"""

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.guards import GuardStateOut, HeartbeatIn
from api.v1.utils import get_simulation_for_user
from apps.common.ratelimit import api_rate_limit
from apps.guards.services import (
    get_guard_state_for_simulation,
    record_heartbeat,
)
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["guards"], auth=DualAuth())


@router.post(
    "/{simulation_id}/heartbeat/",
    response=GuardStateOut,
    summary="Record a client heartbeat",
    description=(
        "Clients send this every 15 seconds to report presence and visibility. "
        "Returns the current guard state for UI rendering."
    ),
)
@api_rate_limit
def heartbeat(
    request: HttpRequest,
    simulation_id: int,
    body: HeartbeatIn,
) -> GuardStateOut:
    """Record a client heartbeat and return current guard state."""
    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    try:
        record_heartbeat(sim.pk, body.client_visibility)
    except Exception:
        logger.exception(
            "guards.heartbeat.failed",
            simulation_id=sim.pk,
        )

    state = get_guard_state_for_simulation(sim.pk)
    return GuardStateOut(**state)


@router.get(
    "/{simulation_id}/guard-state/",
    response=GuardStateOut,
    summary="Get current guard state",
    description="Returns the current guard state for a simulation.",
)
@api_rate_limit
def get_guard_state(
    request: HttpRequest,
    simulation_id: int,
) -> GuardStateOut:
    """Return the current guard state for a simulation."""
    user = request.auth
    sim = get_simulation_for_user(simulation_id, user, request=request)

    state = get_guard_state_for_simulation(sim.pk)
    return GuardStateOut(**state)
