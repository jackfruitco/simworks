from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from config.logging import get_logger

from .models import SessionStatus, TrainerSession
from .services import emit_runtime_event

logger = get_logger(__name__)


@shared_task(bind=True, ignore_result=True)
def trainerlab_runtime_tick(self, session_id: int, tick_nonce: int) -> None:
    """Continuous AI runtime tick loop for TrainerLab sessions.

    The loop is nonce-gated so stale scheduled tasks safely no-op.
    """
    try:
        session = TrainerSession.objects.select_related("simulation").get(pk=session_id)
    except TrainerSession.DoesNotExist:
        return

    if session.tick_nonce != tick_nonce:
        return

    if session.status != SessionStatus.RUNNING:
        return

    now = timezone.now()
    state = dict(session.runtime_state_json or {})
    state["tick_count"] = int(state.get("tick_count", 0)) + 1
    state["last_tick_at"] = now.isoformat()

    session.runtime_state_json = state
    session.last_ai_tick_at = now
    session.save(update_fields=["runtime_state_json", "last_ai_tick_at", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.ai.tick.completed",
        payload={
            "tick_count": state["tick_count"],
            "status": session.status,
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
