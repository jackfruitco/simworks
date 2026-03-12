from __future__ import annotations

from collections import Counter
from datetime import UTC
from typing import Any

from asgiref.sync import async_to_sync
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.common.outbox import enqueue_event_sync, poke_drain_sync
from apps.simcore.models import Simulation
from apps.simcore.utils import generate_fake_name
from config.logging import get_logger

from .models import (
    SessionStatus,
    TrainerCommand,
    TrainerRunSummary,
    TrainerRuntimeEvent,
    TrainerSession,
)

MIN_TICK_INTERVAL = 5
MAX_TICK_INTERVAL = 60
DEFAULT_TICK_INTERVAL = 15
logger = get_logger(__name__)


def _normalize_tick_interval(value: int | None) -> int:
    if value is None:
        return DEFAULT_TICK_INTERVAL
    return max(MIN_TICK_INTERVAL, min(MAX_TICK_INTERVAL, int(value)))


def emit_runtime_event(
    *,
    session: TrainerSession,
    event_type: str,
    payload: dict[str, Any],
    created_by=None,
    supersedes: TrainerRuntimeEvent | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
) -> TrainerRuntimeEvent:
    runtime_event = TrainerRuntimeEvent.objects.create(
        session=session,
        simulation=session.simulation,
        event_type=event_type,
        payload=payload,
        supersedes=supersedes,
        created_by=created_by,
        correlation_id=correlation_id,
    )

    outbox_payload = {
        "session_id": session.id,
        "event_id": str(runtime_event.id),
        **payload,
    }
    event = enqueue_event_sync(
        event_type=event_type,
        simulation_id=session.simulation_id,
        payload=outbox_payload,
        idempotency_key=idempotency_key or f"{event_type}:{runtime_event.id}",
        correlation_id=correlation_id,
    )
    if event:
        poke_drain_sync()

    return runtime_event


def create_session(
    *,
    user,
    scenario_spec: dict[str, Any] | None,
    directives: str | None,
    modifiers: list[str] | None,
) -> TrainerSession:
    scenario_spec = scenario_spec or {}
    modifiers = modifiers or []

    patient_name = async_to_sync(generate_fake_name)()
    diagnosis = scenario_spec.get("diagnosis")
    chief_complaint = scenario_spec.get("chief_complaint")

    simulation = Simulation.objects.create(
        user=user,
        sim_patient_full_name=patient_name,
        diagnosis=diagnosis,
        chief_complaint=chief_complaint,
    )

    session = TrainerSession.objects.create(
        simulation=simulation,
        status=SessionStatus.SEEDED,
        scenario_spec_json={**scenario_spec, "modifiers": modifiers},
        initial_directives=directives or "",
        runtime_state_json={
            "phase": "seeded",
            "last_instruction": directives or "",
            "tick_count": 0,
        },
        tick_interval_seconds=_normalize_tick_interval(scenario_spec.get("tick_interval_seconds")),
    )

    emit_runtime_event(
        session=session,
        event_type="trainerlab.session.seeded",
        payload={
            "status": session.status,
            "scenario_spec": session.scenario_spec_json,
        },
        created_by=user,
    )

    return session


def enqueue_initial_scenario_generation(*, simulation: Simulation) -> str | None:
    """Enqueue initial TrainerLab AI scenario generation for a simulation."""
    from .orca.services import GenerateInitialScenario

    try:
        return GenerateInitialScenario.task.using(
            context={"simulation_id": simulation.id},
        ).enqueue()
    except Exception:
        logger.exception("Initial generation enqueue failed for simulation %s", simulation.id)
        simulation.mark_failed(
            reason_code="initial_generation_enqueue_failed",
            reason_text="We could not start this simulation. Please try again.",
            retryable=True,
        )
        return None


def create_session_with_initial_generation(
    *,
    user,
    scenario_spec: dict[str, Any] | None,
    directives: str | None,
    modifiers: list[str] | None,
) -> tuple[TrainerSession, str | None]:
    """Create a TrainerSession and enqueue initial AI scenario generation."""
    session = create_session(
        user=user,
        scenario_spec=scenario_spec,
        directives=directives,
        modifiers=modifiers,
    )
    call_id = enqueue_initial_scenario_generation(simulation=session.simulation)
    return session, call_id


def get_or_create_command(
    *,
    session: TrainerSession,
    command_type: str,
    idempotency_key: str,
    issued_by,
    payload_json: dict[str, Any] | None = None,
) -> tuple[TrainerCommand, bool]:
    command, created = TrainerCommand.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "session": session,
            "command_type": command_type,
            "payload_json": payload_json or {},
            "issued_by": issued_by,
        },
    )
    return command, created


def _schedule_tick(session: TrainerSession) -> None:
    from .tasks import trainerlab_runtime_tick

    try:
        trainerlab_runtime_tick.apply_async(args=[session.id, session.tick_nonce], countdown=1)
    except Exception:
        logger.exception(
            "trainerlab.tick.schedule_failed",
            session_id=session.id,
            tick_nonce=session.tick_nonce,
        )


def start_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.SEEDED:
        raise ValidationError("Session can only be started from seeded state")

    session.status = SessionStatus.RUNNING
    session.run_started_at = session.run_started_at or timezone.now()
    session.run_paused_at = None
    session.tick_nonce += 1
    session.save(
        update_fields=["status", "run_started_at", "run_paused_at", "tick_nonce", "modified_at"]
    )

    emit_runtime_event(
        session=session,
        event_type="trainerlab.run.started",
        payload={"status": session.status},
        created_by=user,
        correlation_id=correlation_id,
    )
    _schedule_tick(session)
    return session


def pause_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.RUNNING:
        raise ValidationError("Session can only be paused from running state")

    session.status = SessionStatus.PAUSED
    session.run_paused_at = timezone.now()
    session.save(update_fields=["status", "run_paused_at", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.run.paused",
        payload={"status": session.status},
        created_by=user,
        correlation_id=correlation_id,
    )
    return session


def resume_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.PAUSED:
        raise ValidationError("Session can only be resumed from paused state")

    session.status = SessionStatus.RUNNING
    session.run_paused_at = None
    session.tick_nonce += 1
    session.save(update_fields=["status", "run_paused_at", "tick_nonce", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.run.resumed",
        payload={"status": session.status},
        created_by=user,
        correlation_id=correlation_id,
    )
    _schedule_tick(session)
    return session


def stop_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED, SessionStatus.SEEDED}:
        raise ValidationError("Session is already terminal")

    terminal_at = timezone.now()
    session.status = SessionStatus.COMPLETED
    session.run_completed_at = terminal_at
    session.save(update_fields=["status", "run_completed_at", "modified_at"])

    if not session.simulation.is_complete:
        session.simulation.mark_completed()

    emit_runtime_event(
        session=session,
        event_type="trainerlab.run.stopped",
        payload={"status": session.status},
        created_by=user,
        correlation_id=correlation_id,
    )
    build_summary(session=session, generated_by=user)
    return session


@transaction.atomic
def build_summary(*, session: TrainerSession, generated_by=None) -> TrainerRunSummary:
    events = list(session.runtime_events.order_by("created_at"))
    commands = list(session.commands.order_by("issued_at"))

    summary_payload = {
        "session_id": session.id,
        "simulation_id": session.simulation_id,
        "status": session.status,
        "run_started_at": session.run_started_at.astimezone(UTC).isoformat()
        if session.run_started_at
        else None,
        "run_completed_at": session.run_completed_at.astimezone(UTC).isoformat()
        if session.run_completed_at
        else None,
        "final_state": session.runtime_state_json,
        "event_type_counts": dict(Counter(event.event_type for event in events)),
        "timeline_highlights": [
            {
                "event_type": event.event_type,
                "created_at": event.created_at.astimezone(UTC).isoformat(),
                "payload": event.payload,
            }
            for event in events[-10:]
        ],
        "command_log": [
            {
                "id": str(command.id),
                "command_type": command.command_type,
                "status": command.status,
                "issued_at": command.issued_at.astimezone(UTC).isoformat(),
                "payload": command.payload_json,
            }
            for command in commands
        ],
        "ai_rationale_notes": session.runtime_state_json.get("ai_rationale_notes", []),
    }

    summary, _ = TrainerRunSummary.objects.update_or_create(
        session=session,
        defaults={
            "summary_json": summary_payload,
            "generator_version": "v1",
        },
    )

    emit_runtime_event(
        session=session,
        event_type="trainerlab.summary.ready",
        payload={"summary_id": summary.id},
        created_by=generated_by,
    )

    return summary
