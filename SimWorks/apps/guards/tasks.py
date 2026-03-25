"""Periodic Celery tasks for server-side guard enforcement.

These tasks run independently of client heartbeats to ensure the server
remains authoritative for pause transitions.
"""

from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from config.logging import get_logger

from .enums import GuardState, LabType
from .models import SessionPresence

logger = get_logger(__name__)

# Guard states that should be checked for inactivity / wall-clock.
_ACTIVE_GUARD_STATES = frozenset(
    {GuardState.ACTIVE, GuardState.IDLE, GuardState.WARNING}
)


@shared_task(ignore_result=True)
def check_stale_sessions() -> int:
    """Periodic task: evaluate inactivity and wall-clock for all active sessions.

    Designed to run every 15 seconds via Celery Beat.
    Returns the number of sessions that transitioned.
    """
    transitions = 0

    # Find all active TrainerLab sessions that may need inactivity checks.
    stale_candidates = SessionPresence.objects.filter(
        lab_type=LabType.TRAINERLAB,
        guard_state__in=_ACTIVE_GUARD_STATES,
    ).values_list("simulation_id", flat=True)

    for simulation_id in stale_candidates:
        from .services import evaluate_inactivity

        new_state = evaluate_inactivity(simulation_id)
        if new_state is not None:
            transitions += 1

    # Check wall-clock expiry for all active sessions (any lab type).
    wall_clock_candidates = SessionPresence.objects.filter(
        guard_state__in=_ACTIVE_GUARD_STATES,
        wall_clock_expires_at__isnull=False,
        wall_clock_expires_at__lte=timezone.now(),
    ).values_list("simulation_id", flat=True)

    for simulation_id in wall_clock_candidates:
        from .services import evaluate_wall_clock

        new_state = evaluate_wall_clock(simulation_id)
        if new_state is not None:
            transitions += 1

    if transitions:
        logger.info("guards.stale_check.transitions", count=transitions)

    return transitions


@shared_task(ignore_result=True)
def check_session_inactivity(simulation_id: int) -> str | None:
    """Evaluate inactivity for a single session.

    Can be called on-demand or scheduled per-session.
    """
    from .services import evaluate_inactivity

    new_state = evaluate_inactivity(simulation_id)
    return new_state if new_state else None
