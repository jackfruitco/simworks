from __future__ import annotations

from celery import shared_task
from django.tasks import task
from django.utils import timezone

from config.logging import get_logger

from .models import SessionStatus, TrainerSession
from .services import append_pending_runtime_reason, process_runtime_turn_queue

logger = get_logger(__name__)

# Grace period before a failed TrainerLab simulation is auto-archived.
FAILED_SIMULATION_ARCHIVE_AFTER_SECONDS = 300


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


@shared_task(ignore_result=True)
def archive_failed_trainerlab_simulations() -> None:
    """Archive failed TrainerLab simulations that have passed the grace period.

    Runs periodically via Celery beat.  Only targets simulations that:
      - have status=FAILED
      - reached terminal_at more than FAILED_SIMULATION_ARCHIVE_AFTER_SECONDS ago
      - are not yet archived
      - have an associated TrainerSession (TrainerLab-owned only)
    """
    from datetime import timedelta

    from apps.common.utils import get_system_user
    from apps.simcore.models import Simulation

    cutoff = timezone.now() - timedelta(seconds=FAILED_SIMULATION_ARCHIVE_AFTER_SECONDS)
    qs = Simulation.objects.filter(
        status=Simulation.SimulationStatus.FAILED,
        terminal_at__lte=cutoff,
        archived_at__isnull=True,
        trainerlab_session__isnull=False,
    )

    system_user = None
    try:
        system_user = get_system_user()
    except Exception:
        logger.exception("archive_failed_trainerlab_simulations.system_user_error")

    archived_count = 0
    for simulation in qs.iterator():
        try:
            simulation.archive(
                reason=Simulation.ArchiveReason.SYSTEM_FAILED,
                archived_by=system_user,
            )
            archived_count += 1
        except Exception:
            logger.exception(
                "archive_failed_trainerlab_simulations.archive_error",
                simulation_id=simulation.pk,
            )

    if archived_count:
        logger.info(
            "archive_failed_trainerlab_simulations.done",
            archived_count=archived_count,
        )
