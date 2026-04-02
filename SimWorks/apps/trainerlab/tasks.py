from __future__ import annotations

from celery import shared_task
from django.tasks import task
from django.utils import timezone

from config.logging import get_logger

from .models import SessionStatus, TrainerSession
from .services import append_pending_runtime_reason, process_runtime_turn_queue

logger = get_logger(__name__)


@task
def trainerlab_process_runtime_turn(*, session_id: int) -> str | None:
    """Claim any pending runtime reasons and enqueue one AI runtime turn."""
    return process_runtime_turn_queue(session_id=session_id)


@shared_task(bind=True, ignore_result=True)
def trainerlab_runtime_tick(self, session_id: int, tick_nonce: int) -> None:
    """Continuous runtime scheduler for TrainerLab sessions.

    The recurring task only records that active time advanced; the AI-facing
    processing happens in the single-flight runtime worker.
    """
    try:
        session = TrainerSession.objects.select_related("simulation").get(pk=session_id)
    except TrainerSession.DoesNotExist:
        return

    if session.tick_nonce != tick_nonce:
        return

    if session.status != SessionStatus.RUNNING:
        return

    # ── Guard: evaluate runtime cap on each tick ────────────────────
    from .services import get_active_elapsed_seconds

    active_elapsed = get_active_elapsed_seconds(session)
    try:
        from apps.guards.services import evaluate_runtime_cap

        new_state = evaluate_runtime_cap(session.simulation_id, active_elapsed)
        if new_state is not None:
            # Runtime cap reached: evaluate_runtime_cap() already transitioned
            # guard state to PAUSED_RUNTIME_CAP.  Now pause the TrainerLab
            # session so the tick loop stops and elapsed time is frozen.
            # _sync_guard_pause inside pause_session() will short-circuit because
            # guard state is already in NON_RUNNABLE_STATES.
            from .services import pause_session

            session.refresh_from_db()
            if session.status == SessionStatus.RUNNING:
                pause_session(session=session, user=None, correlation_id=None)
            logger.info(
                "trainerlab.tick.runtime_cap_reached",
                session_id=session.id,
                active_elapsed=active_elapsed,
            )
            return  # Do not reschedule tick.
    except Exception:
        logger.exception(
            "trainerlab.tick.guard_eval_failed",
            session_id=session.id,
        )

    append_pending_runtime_reason(
        session=session,
        reason_kind="tick",
        payload={
            "tick_nonce": tick_nonce,
            "scheduled_at": timezone.now().isoformat(),
        },
    )

    try:
        trainerlab_runtime_tick.apply_async(
            args=[session.id, tick_nonce],
            countdown=session.tick_interval_seconds,
        )
    except Exception:
        logger.exception(
            "trainerlab.tick.reschedule_failed",
            session_id=session.id,
            tick_nonce=tick_nonce,
        )
