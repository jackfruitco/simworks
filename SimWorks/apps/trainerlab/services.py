from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from asgiref.sync import async_to_sync
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.outbox import enqueue_event_sync, poke_drain_sync
from apps.simcore.models import Simulation
from apps.simcore.utils import generate_fake_name
from config.logging import get_logger

from .models import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    DebriefAnnotation,
    EventSource,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    Problem,
    PulseAssessment,
    RespiratoryRate,
    RuntimeEvent,
    ScenarioBrief,
    SessionStatus,
    SimulationNote,
    TrainerCommand,
    TrainerRunSummary,
    TrainerSession,
)

MIN_TICK_INTERVAL = 5
MAX_TICK_INTERVAL = 60
DEFAULT_TICK_INTERVAL = 15
RUNTIME_BATCH_SIZE = 25
TERMINAL_SESSION_STATUSES = {SessionStatus.COMPLETED, SessionStatus.FAILED}
logger = get_logger(__name__)

VITAL_TYPE_MODEL_MAP = {
    "heart_rate": HeartRate,
    "respiratory_rate": RespiratoryRate,
    "spo2": SPO2,
    "etco2": ETCO2,
    "blood_glucose": BloodGlucoseLevel,
    "blood_pressure": BloodPressure,
}


def _normalize_tick_interval(value: int | None) -> int:
    if value is None:
        return DEFAULT_TICK_INTERVAL
    return max(MIN_TICK_INTERVAL, min(MAX_TICK_INTERVAL, int(value)))


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, UTC)
    return parsed


def build_runtime_state_defaults(
    *,
    directives: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = {
        "phase": "seeded",
        "last_instruction": directives,
        "tick_count": 0,
        "state_revision": 0,
        "active_elapsed_seconds": 0,
        "active_elapsed_anchor_started_at": None,
        "scenario_brief": {
            "read_aloud_brief": "Scenario brief pending.",
            "environment": "",
            "location_overview": "",
            "threat_context": "",
            "evacuation_options": [],
            "evacuation_time": "",
            "special_considerations": [],
        },
        "current_snapshot": {
            "conditions": [],
            "interventions": [],
            "vitals": [],
            "pulses": [],
            "patient_status": {},
        },
        "snapshot_annotations": {"patient_status": {}},
        "ai_plan": {
            "summary": "",
            "rationale": "",
            "trigger": "",
            "eta_seconds": None,
            "confidence": 0.0,
            "upcoming_changes": [],
            "monitoring_focus": [],
        },
        "ai_rationale_notes": [],
        "pending_runtime_reasons": [],
        "currently_processing_reasons": [],
        "runtime_processing": False,
        "intervention_effects": {},
        "last_runtime_enqueued_at": None,
        "last_runtime_completed_at": None,
        "last_runtime_error": "",
        "last_processed_runtime_reasons": [],
        "last_discarded_runtime_reasons": [],
        "last_runtime_discarded_at": None,
        "summary_feedback": {},
    }
    merged = dict(baseline)
    if state:
        merged.update(state)
        merged["current_snapshot"] = {
            **baseline["current_snapshot"],
            **dict(state.get("current_snapshot") or {}),
        }
        merged["snapshot_annotations"] = {
            **baseline["snapshot_annotations"],
            **dict(state.get("snapshot_annotations") or {}),
        }
        merged["ai_plan"] = {
            **baseline["ai_plan"],
            **dict(state.get("ai_plan") or {}),
        }
        merged["scenario_brief"] = {
            **baseline["scenario_brief"],
            **dict(state.get("scenario_brief") or {}),
        }
    return merged


def get_runtime_state(session: TrainerSession) -> dict[str, Any]:
    return build_runtime_state_defaults(
        directives=session.initial_directives or "",
        state=dict(session.runtime_state_json or {}),
    )


def get_active_elapsed_seconds(
    session: TrainerSession,
    *,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    state = build_runtime_state_defaults(
        directives=session.initial_directives or "",
        state=state or session.runtime_state_json or {},
    )
    now = now or timezone.now()
    elapsed = int(state.get("active_elapsed_seconds", 0) or 0)
    anchor = _parse_iso_datetime(state.get("active_elapsed_anchor_started_at"))
    if session.status == SessionStatus.RUNNING and anchor is not None:
        elapsed += max(0, int((now - anchor).total_seconds()))
    return elapsed


def _set_active_elapsed_anchor(
    session: TrainerSession,
    *,
    state: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or timezone.now()
    state = build_runtime_state_defaults(directives=session.initial_directives or "", state=state)
    state["active_elapsed_anchor_started_at"] = now.astimezone(UTC).isoformat()
    return state


def _freeze_active_elapsed(
    session: TrainerSession,
    *,
    state: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or timezone.now()
    state = build_runtime_state_defaults(directives=session.initial_directives or "", state=state)
    state["active_elapsed_seconds"] = get_active_elapsed_seconds(session, state=state, now=now)
    state["active_elapsed_anchor_started_at"] = None
    return state


def emit_runtime_event(
    *,
    session: TrainerSession,
    event_type: str,
    payload: dict[str, Any],
    created_by=None,
    supersedes: RuntimeEvent | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
) -> RuntimeEvent:
    runtime_event = RuntimeEvent.objects.create(
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


def _problem_control_state(problem: Problem) -> str:
    if problem.is_resolved:
        return "resolved"
    if problem.is_treated:
        return "controlled"
    return "uncontrolled"


def _serialize_condition(problem: Problem, cause: Injury | Illness | None) -> dict[str, Any]:
    """Serialize a Problem (lifecycle record) with its underlying cause."""
    payload = {
        "domain_event_id": problem.id,
        "problem_id": problem.id,
        "cause_event_id": problem.cause_id,
        "source": problem.source,
        "supersedes_event_id": problem.supersedes_id,
        "timestamp": _iso_or_none(problem.timestamp),
        "kind": problem.problem_kind,
        "march_category": problem.march_category,
        "severity": problem.severity,
        "is_treated": problem.is_treated,
        "is_resolved": problem.is_resolved,
        "control_state": _problem_control_state(problem),
        "status": "resolved" if problem.is_resolved else "active",
        "description": problem.description,
    }
    if isinstance(cause, Injury):
        payload.update(
            {
                "label": cause.injury_description,
                "injury_location": cause.injury_location,
                "injury_kind": cause.injury_kind,
                "injury_location_label": cause.get_injury_location_display(),
                "injury_kind_label": cause.get_injury_kind_display(),
            }
        )
    elif isinstance(cause, Illness):
        payload.update(
            {
                "label": cause.name,
                "name": cause.name,
                "illness_description": cause.description,
            }
        )
    else:
        payload["label"] = problem.description or "Unknown condition"
    return payload


def _serialize_intervention(
    obj: Intervention,
    *,
    intervention_effects: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effect = dict((intervention_effects or {}).get(str(obj.id), {}))
    return {
        "domain_event_id": obj.id,
        "intervention_type": obj.intervention_type or None,
        "site_code": obj.site_code or None,
        "effectiveness": obj.effectiveness,
        "notes": obj.notes,
        "code": obj.code,
        "description": obj.description,
        "target": obj.target,
        "anatomic_location": obj.anatomic_location,
        "performed_by_role": obj.performed_by_role,
        "source": obj.source,
        "timestamp": _iso_or_none(obj.timestamp),
        "status": effect.get("status", "active"),
        "clinical_effect": effect.get("clinical_effect", ""),
    }


def _serialize_vital(vital_type: str, obj: Any) -> dict[str, Any]:
    payload = {
        "domain_event_id": obj.id,
        "vital_type": vital_type,
        "min_value": getattr(obj, "min_value", None),
        "max_value": getattr(obj, "max_value", None),
        "lock_value": getattr(obj, "lock_value", None),
        "timestamp": _iso_or_none(obj.timestamp),
        "source": obj.source,
        "trend": "stable",
    }
    if isinstance(obj, BloodPressure):
        payload["min_value_diastolic"] = obj.min_value_diastolic
        payload["max_value_diastolic"] = obj.max_value_diastolic
    return payload


def _serialize_pulse(obj: PulseAssessment) -> dict[str, Any]:
    return {
        "domain_event_id": obj.id,
        "vital_type": "pulse_assessment",
        "location": obj.location,
        "present": obj.present,
        "description": obj.description,
        "color_normal": obj.color_normal,
        "color_description": obj.color_description,
        "condition_normal": obj.condition_normal,
        "condition_description": obj.condition_description,
        "temperature_normal": obj.temperature_normal,
        "temperature_description": obj.temperature_description,
        "timestamp": _iso_or_none(obj.timestamp),
        "source": obj.source,
    }


def project_current_snapshot(
    session: TrainerSession,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = (
        get_runtime_state(session)
        if state is None
        else build_runtime_state_defaults(
            directives=session.initial_directives or "",
            state=state,
        )
    )

    problems = list(
        Problem.objects.select_related("cause_injury", "cause_illness")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    conditions = [_serialize_condition(p, p.cause) for p in problems]

    interventions = [
        _serialize_intervention(
            item,
            intervention_effects=dict(state.get("intervention_effects") or {}),
        )
        for item in Intervention.objects.filter(
            simulation=session.simulation,
            is_active=True,
        ).order_by("timestamp", "id")
    ]

    vitals: list[dict[str, Any]] = []
    for vital_type, model in VITAL_TYPE_MODEL_MAP.items():
        current = (
            model.objects.filter(
                simulation=session.simulation,
                is_active=True,
            )
            .order_by("-timestamp", "-id")
            .first()
        )
        if current is not None:
            vitals.append(_serialize_vital(vital_type, current))

    scenario_brief_data: dict[str, Any] = {}
    scenario_brief_obj = (
        ScenarioBrief.objects.filter(
            simulation=session.simulation,
            is_active=True,
        )
        .order_by("-timestamp", "-id")
        .first()
    )
    if scenario_brief_obj is not None:
        scenario_brief_data = {
            "read_aloud_brief": scenario_brief_obj.read_aloud_brief,
            "environment": scenario_brief_obj.environment,
            "location_overview": scenario_brief_obj.location_overview,
            "threat_context": scenario_brief_obj.threat_context,
            "evacuation_options": scenario_brief_obj.evacuation_options,
            "evacuation_time": scenario_brief_obj.evacuation_time,
            "special_considerations": scenario_brief_obj.special_considerations,
        }

    pulses: list[dict[str, Any]] = [
        _serialize_pulse(obj)
        for obj in PulseAssessment.objects.filter(
            simulation=session.simulation,
            is_active=True,
        ).order_by("location")
    ]

    return {
        "conditions": conditions,
        "interventions": interventions,
        "vitals": vitals,
        "pulses": pulses,
        "patient_status": dict(
            (state.get("snapshot_annotations") or {}).get("patient_status") or {}
        ),
        "scenario_brief": scenario_brief_data,
    }


def refresh_runtime_projection(
    *,
    session: TrainerSession,
    correlation_id: str | None = None,
    ai_plan: dict[str, Any] | None = None,
    rationale_notes: list[str] | None = None,
    snapshot_annotations: dict[str, Any] | None = None,
    processed_reasons: list[dict[str, Any]] | None = None,
    update_tick_timestamp: bool = False,
) -> dict[str, Any]:
    now = timezone.now()
    state = get_runtime_state(session)

    if snapshot_annotations is not None:
        state["snapshot_annotations"] = {
            **dict(state.get("snapshot_annotations") or {}),
            **snapshot_annotations,
        }
    if ai_plan is not None:
        state["ai_plan"] = {
            **dict(state.get("ai_plan") or {}),
            **ai_plan,
        }
    if rationale_notes is not None:
        state["ai_rationale_notes"] = list(rationale_notes)
    if processed_reasons is not None:
        state["last_processed_runtime_reasons"] = list(processed_reasons)
        tick_count = sum(1 for reason in processed_reasons if reason.get("reason_kind") == "tick")
        if tick_count:
            state["tick_count"] = int(state.get("tick_count", 0) or 0) + tick_count

    state["active_elapsed_seconds"] = get_active_elapsed_seconds(session, state=state, now=now)
    snapshot = project_current_snapshot(session, state=state)
    state["current_snapshot"] = snapshot
    # Promote scenario_brief from snapshot to top-level state for backward compat
    if snapshot.get("scenario_brief"):
        state["scenario_brief"] = snapshot["scenario_brief"]
    state["state_revision"] = int(state.get("state_revision", 0) or 0) + 1
    state["last_runtime_completed_at"] = now.astimezone(UTC).isoformat()

    session.runtime_state_json = state
    update_fields = ["runtime_state_json", "modified_at"]
    if update_tick_timestamp:
        session.last_ai_tick_at = now
        update_fields.append("last_ai_tick_at")
    session.save(update_fields=update_fields)

    emit_runtime_event(
        session=session,
        event_type="state.updated",
        payload={
            "state_revision": state["state_revision"],
            "active_elapsed_seconds": state["active_elapsed_seconds"],
            "scenario_brief": state["scenario_brief"],
            "current_snapshot": state["current_snapshot"],
            "processed_reasons": processed_reasons or [],
        },
        correlation_id=correlation_id,
        idempotency_key=f"state.updated:{session.id}:{state['state_revision']}",
    )

    emit_runtime_event(
        session=session,
        event_type="ai.intent.updated",
        payload={
            "state_revision": state["state_revision"],
            "ai_plan": state["ai_plan"],
        },
        correlation_id=correlation_id,
        idempotency_key=f"ai.intent.updated:{session.id}:{state['state_revision']}",
    )
    return state


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

    initial_state = build_runtime_state_defaults(directives=directives or "")
    session = TrainerSession.objects.create(
        simulation=simulation,
        status=SessionStatus.SEEDED,
        scenario_spec_json={**scenario_spec, "modifiers": modifiers},
        initial_directives=directives or "",
        runtime_state_json=initial_state,
        tick_interval_seconds=_normalize_tick_interval(scenario_spec.get("tick_interval_seconds")),
    )

    emit_runtime_event(
        session=session,
        event_type="session.seeded",
        payload={
            "status": session.status,
            "scenario_spec": session.scenario_spec_json,
            "state_revision": initial_state["state_revision"],
        },
        created_by=user,
    )

    return session


def enqueue_initial_scenario_generation(*, simulation: Simulation) -> str | None:
    from .orca.services import GenerateInitialScenario

    try:
        return GenerateInitialScenario.task.using(
            context={"simulation_id": simulation.id},
        ).enqueue(
            user_message="Generate the initial TrainerLab scenario state.",
        )
    except Exception:
        logger.exception("Initial generation enqueue failed for simulation %s", simulation.id)
        simulation.mark_failed(
            reason_code="trainerlab_initial_generation_enqueue_failed",
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
    session = create_session(
        user=user,
        scenario_spec=scenario_spec,
        directives=directives,
        modifiers=modifiers,
    )
    call_id = enqueue_initial_scenario_generation(simulation=session.simulation)
    if call_id:
        _run_initial_generation_inline(session=session, call_id=call_id)
    return session, call_id


def _run_initial_generation_inline(*, session: TrainerSession, call_id: str) -> None:
    """Run initial scenario generation synchronously so the session is fully seeded on return.

    The background task dispatched by enqueue_initial_scenario_generation() will see
    the call already completed and return early — run_service_call() is idempotent.
    """
    from orchestrai_django.tasks import run_service_call

    try:
        run_service_call(call_id)
    except Exception:
        logger.exception(
            "Inline initial generation failed for simulation %s",
            session.simulation_id,
        )
        return

    # Emit TrainerRuntimeEvent records so vitals/conditions are queryable via the event stream.
    # OutboxEvents for SSE delivery were already created by post_persist() →
    # broadcast_domain_objects(); these records serve the catch-up API consumers.
    try:
        session.refresh_from_db()
        _emit_seeded_vital_events(session)
        _emit_seeded_condition_events(session)
        _emit_seeded_pulse_events(session)
    except Exception:
        logger.exception(
            "Failed to emit seeded runtime events for simulation %s",
            session.simulation_id,
        )


def _emit_seeded_vital_events(session: TrainerSession) -> None:
    for vital_type, model in VITAL_TYPE_MODEL_MAP.items():
        obj = (
            model.objects.filter(simulation=session.simulation, is_active=True)
            .order_by("-timestamp", "-id")
            .first()
        )
        if obj is not None:
            emit_runtime_event(
                session=session,
                event_type="vital.created",
                payload=_serialize_vital(vital_type, obj),
                idempotency_key=f"vital.created:seeded:{session.id}:{vital_type}",
            )


def _emit_seeded_pulse_events(session: TrainerSession) -> None:
    for obj in PulseAssessment.objects.filter(
        simulation=session.simulation, is_active=True
    ).order_by("location"):
        emit_runtime_event(
            session=session,
            event_type="trainerlab.pulse.created",
            payload=_serialize_pulse(obj),
            idempotency_key=f"trainerlab.pulse.created:seeded:{session.id}:{obj.location}",
        )


def _emit_seeded_condition_events(session: TrainerSession) -> None:
    problems = list(
        Problem.objects.select_related("cause_injury", "cause_illness")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    for problem in problems:
        emit_runtime_event(
            session=session,
            event_type="condition.created",
            payload=_serialize_condition(problem, problem.cause),
            idempotency_key=f"condition.created:seeded:{session.id}:{problem.id}",
        )


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


def _schedule_runtime_turn(session_id: int) -> None:
    from .tasks import trainerlab_process_runtime_turn

    try:
        trainerlab_process_runtime_turn.enqueue(session_id=session_id)
    except Exception:
        logger.exception("trainerlab.runtime.schedule_failed", session_id=session_id)


def discard_runtime_work(
    state: dict[str, Any],
    *,
    discarded_at: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    discarded = list(state.get("currently_processing_reasons") or []) + list(
        state.get("pending_runtime_reasons") or []
    )
    state["pending_runtime_reasons"] = []
    state["currently_processing_reasons"] = []
    state["runtime_processing"] = False
    state["last_runtime_error"] = ""
    state["last_discarded_runtime_reasons"] = discarded
    state["last_runtime_discarded_at"] = _iso_or_none(discarded_at or timezone.now())
    return state, discarded


@transaction.atomic
def append_pending_runtime_reason(
    *,
    session: TrainerSession,
    reason_kind: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    locked = TrainerSession.objects.select_for_update().get(pk=session.pk)
    state = get_runtime_state(locked)
    reason = {
        "reason_kind": reason_kind,
        "payload": payload or {},
        "created_at": timezone.now().astimezone(UTC).isoformat(),
        "correlation_id": correlation_id,
    }
    pending = list(state.get("pending_runtime_reasons") or [])
    pending.append(reason)
    state["pending_runtime_reasons"] = pending
    state["last_runtime_error"] = ""
    locked.runtime_state_json = state
    locked.save(update_fields=["runtime_state_json", "modified_at"])
    transaction.on_commit(lambda: _schedule_runtime_turn(locked.id))
    return reason


def _claim_runtime_turn_batch(session_id: int) -> dict[str, Any] | None:
    with transaction.atomic():
        session = (
            TrainerSession.objects.select_for_update()
            .select_related("simulation")
            .get(pk=session_id)
        )
        state = get_runtime_state(session)
        if session.status in TERMINAL_SESSION_STATUSES:
            current = list(state.get("currently_processing_reasons") or [])
            pending = list(state.get("pending_runtime_reasons") or [])
            if current or pending or state.get("runtime_processing"):
                state, _discarded = discard_runtime_work(state)
                session.runtime_state_json = state
                session.save(update_fields=["runtime_state_json", "modified_at"])
            return None

        if state.get("runtime_processing"):
            return None

        pending = list(state.get("pending_runtime_reasons") or [])
        if not pending:
            return None

        if session.status == SessionStatus.RUNNING:
            reasons = pending[:RUNTIME_BATCH_SIZE]
            remaining = pending[RUNTIME_BATCH_SIZE:]
        else:
            reasons = [item for item in pending if item.get("reason_kind") != "tick"][
                :RUNTIME_BATCH_SIZE
            ]
            skipped_tick_ids = {id(item) for item in pending if item.get("reason_kind") == "tick"}
            remaining = [
                item for item in pending if item not in reasons and id(item) not in skipped_tick_ids
            ]

        if not reasons:
            state["pending_runtime_reasons"] = remaining
            session.runtime_state_json = state
            session.save(update_fields=["runtime_state_json", "modified_at"])
            return None

        active_elapsed_seconds = get_active_elapsed_seconds(session, state=state)
        state["pending_runtime_reasons"] = remaining
        state["currently_processing_reasons"] = reasons
        state["runtime_processing"] = True
        state["last_runtime_enqueued_at"] = timezone.now().astimezone(UTC).isoformat()
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])

        return {
            "session_id": session.id,
            "simulation_id": session.simulation_id,
            "reasons": reasons,
            "active_elapsed_seconds": active_elapsed_seconds,
            "current_snapshot": project_current_snapshot(session, state=state),
            "correlation_id": next(
                (
                    reason.get("correlation_id")
                    for reason in reversed(reasons)
                    if reason.get("correlation_id")
                ),
                None,
            ),
            "status": session.status,
        }


def _restore_runtime_turn_batch(
    *,
    session_id: int,
    reasons: list[dict[str, Any]],
    error: str,
) -> None:
    with transaction.atomic():
        session = TrainerSession.objects.select_for_update().get(pk=session_id)
        state = get_runtime_state(session)
        pending = list(state.get("pending_runtime_reasons") or [])
        state["pending_runtime_reasons"] = reasons + pending
        state["currently_processing_reasons"] = []
        state["runtime_processing"] = False
        state["last_runtime_error"] = error[:500]
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])


def enqueue_runtime_turn_service_call(batch: dict[str, Any]) -> str:
    from .orca.services import GenerateTrainerRuntimeTurn

    return GenerateTrainerRuntimeTurn.task.using(
        context={
            "simulation_id": batch["simulation_id"],
            "session_id": batch["session_id"],
            "runtime_reasons": batch["reasons"],
            "active_elapsed_seconds": batch["active_elapsed_seconds"],
            "current_snapshot": batch["current_snapshot"],
            "correlation_id": batch.get("correlation_id"),
        },
    ).enqueue(
        user_message="Process the next TrainerLab runtime turn and return the authoritative patient update.",
    )


def process_runtime_turn_queue(*, session_id: int) -> str | None:
    batch = _claim_runtime_turn_batch(session_id)
    if batch is None:
        return None

    try:
        return enqueue_runtime_turn_service_call(batch)
    except Exception as exc:
        logger.exception("trainerlab.runtime.enqueue_failed", session_id=session_id)
        _restore_runtime_turn_batch(
            session_id=session_id,
            reasons=batch["reasons"],
            error=str(exc),
        )
        session = TrainerSession.objects.select_related("simulation").get(pk=session_id)
        emit_runtime_event(
            session=session,
            event_type="runtime.failed",
            payload={
                "error": str(exc),
                "reasons": batch["reasons"],
            },
            correlation_id=batch.get("correlation_id"),
            idempotency_key=f"runtime.failed:{session.id}:{timezone.now().timestamp()}",
        )
        raise


def clear_runtime_processing(
    *,
    session_id: int,
    error: str = "",
    requeue_current_batch: bool = False,
) -> None:
    with transaction.atomic():
        session = TrainerSession.objects.select_for_update().get(pk=session_id)
        state = get_runtime_state(session)
        current = list(state.get("currently_processing_reasons") or [])
        pending = list(state.get("pending_runtime_reasons") or [])
        if session.status in TERMINAL_SESSION_STATUSES:
            requeue_current_batch = False
        if requeue_current_batch and current:
            pending = current + pending
        state["pending_runtime_reasons"] = pending
        state["currently_processing_reasons"] = []
        state["runtime_processing"] = False
        state["last_runtime_error"] = error[:500]
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])


def _event_payload_for_condition(
    problem: Problem,
    cause: Injury | Illness | None,
    *,
    action: str,
) -> dict[str, Any]:
    payload = _serialize_condition(problem, cause)
    payload["action"] = action
    return payload


def _emit_condition_change(
    *,
    session: TrainerSession,
    problem: Problem,
    cause: Injury | Illness | None,
    action: str,
    correlation_id: str | None,
) -> None:
    emit_runtime_event(
        session=session,
        event_type=f"condition.{action}",
        payload=_event_payload_for_condition(problem, cause, action=action),
        correlation_id=correlation_id,
        idempotency_key=f"condition.{action}:{problem.id}",
    )


def _resolve_superseded_event(
    *,
    session: TrainerSession,
    target_event_id: int | None,
    expected_model: type,
) -> Any | None:
    if not target_event_id:
        return None
    return expected_model.objects.filter(
        pk=target_event_id,
        simulation=session.simulation,
    ).first()


def _deactivate_event(event: Any | None) -> None:
    if event is None or not event.is_active:
        return
    event.is_active = False
    event.save(update_fields=["is_active"])


def _apply_condition_change(
    *,
    session: TrainerSession,
    change: dict[str, Any],
    correlation_id: str | None,
) -> None:
    action = change.get("action")
    condition_kind = change.get("condition_kind")
    target_event_id = change.get("target_event_id")

    # target_event_id now references a Problem (not Injury/Illness directly).
    source_problem: Problem | None = None
    if target_event_id:
        source_problem = Problem.objects.filter(
            pk=target_event_id, simulation=session.simulation
        ).first()

    if action in {"update", "resolve"}:
        _deactivate_event(source_problem)

    emit_action = (
        "resolved" if action == "resolve" else ("updated" if action == "update" else "created")
    )

    if condition_kind == "injury":
        if action == "resolve" and source_problem is None:
            return

        # For resolve: keep existing cause; only create a new Problem record.
        # For create/update: create a new Injury cause.
        old_cause_injury: Injury | None = source_problem.cause_injury if source_problem else None

        if action == "resolve":
            new_injury = old_cause_injury
        else:
            if action == "update" and old_cause_injury:
                _deactivate_event(old_cause_injury)
            new_injury = Injury.objects.create(
                simulation=session.simulation,
                source=EventSource.AI,
                supersedes=old_cause_injury,
                injury_location=change.get("injury_location")
                or getattr(
                    old_cause_injury,
                    "injury_location",
                    Injury.InjuryLocation.THORAX_LEFT_ANTERIOR,
                ),
                injury_kind=change.get("injury_kind")
                or getattr(old_cause_injury, "injury_kind", Injury.InjuryKind.LACERATION),
                injury_description=change.get("injury_description")
                or getattr(old_cause_injury, "injury_description", "Updated injury"),
            )

        new_problem = Problem.objects.create(
            simulation=session.simulation,
            source=EventSource.AI,
            supersedes=source_problem,
            cause_injury=new_injury,
            problem_kind=Problem.ProblemKind.INJURY,
            march_category=change.get("march_category")
            or getattr(source_problem, "march_category", Problem.MARCHCategory.M),
            severity=change.get("severity")
            or getattr(source_problem, "severity", Problem.Severity.MODERATE),
            is_treated=getattr(source_problem, "is_treated", False),
            is_resolved=action == "resolve",
        )
        _emit_condition_change(
            session=session,
            problem=new_problem,
            cause=new_injury,
            action=emit_action,
            correlation_id=correlation_id,
        )
        return

    # illness branch
    if action == "resolve" and source_problem is None:
        return

    old_cause_illness: Illness | None = source_problem.cause_illness if source_problem else None

    if action == "resolve":
        new_illness = old_cause_illness
    else:
        if action == "update" and old_cause_illness:
            _deactivate_event(old_cause_illness)
        new_illness = Illness.objects.create(
            simulation=session.simulation,
            source=EventSource.AI,
            supersedes=old_cause_illness,
            name=change.get("name") or getattr(old_cause_illness, "name", "Emergent condition"),
            description=change.get("description") or getattr(old_cause_illness, "description", ""),
        )

    new_problem = Problem.objects.create(
        simulation=session.simulation,
        source=EventSource.AI,
        supersedes=source_problem,
        cause_illness=new_illness,
        problem_kind=Problem.ProblemKind.ILLNESS,
        march_category=change.get("march_category")
        or getattr(source_problem, "march_category", Problem.MARCHCategory.R),
        severity=change.get("severity")
        or getattr(source_problem, "severity", Problem.Severity.MODERATE),
        is_treated=getattr(source_problem, "is_treated", False),
        is_resolved=action == "resolve",
    )
    _emit_condition_change(
        session=session,
        problem=new_problem,
        cause=new_illness,
        action=emit_action,
        correlation_id=correlation_id,
    )


def _apply_vital_change(
    *,
    session: TrainerSession,
    change: dict[str, Any],
    correlation_id: str | None,
) -> None:
    vital_type = change.get("vital_type")
    model = VITAL_TYPE_MODEL_MAP.get(vital_type)
    if model is None:
        return

    existing = (
        model.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    _deactivate_event(existing)

    common = {
        "simulation": session.simulation,
        "source": EventSource.AI,
        "supersedes": existing,
        "min_value": change.get("min_value"),
        "max_value": change.get("max_value"),
        "lock_value": bool(change.get("lock_value", False)),
    }
    if model is BloodPressure:
        created = model.objects.create(
            **common,
            min_value_diastolic=change.get("min_value_diastolic"),
            max_value_diastolic=change.get("max_value_diastolic"),
        )
    else:
        created = model.objects.create(**common)

    payload = _serialize_vital(vital_type, created)
    payload["action"] = "updated"
    payload["trend"] = change.get("trend", "stable")
    emit_runtime_event(
        session=session,
        event_type="vital.updated",
        payload=payload,
        correlation_id=correlation_id,
        idempotency_key=f"vital.updated:{created.id}",
    )


def _apply_pulse_change(
    *,
    session: TrainerSession,
    change: dict[str, Any],
    correlation_id: str | None,
) -> None:
    location = change.get("location")
    if not location:
        return

    existing = (
        PulseAssessment.objects.filter(
            simulation=session.simulation,
            location=location,
            is_active=True,
        )
        .order_by("-timestamp", "-id")
        .first()
    )
    _deactivate_event(existing)

    created = PulseAssessment.objects.create(
        simulation=session.simulation,
        source=EventSource.AI,
        supersedes=existing,
        location=location,
        present=bool(change.get("present", True)),
        description=change.get("description", "strong"),
        color_normal=bool(change.get("color_normal", True)),
        color_description=change.get("color_description", "pink"),
        condition_normal=bool(change.get("condition_normal", True)),
        condition_description=change.get("condition_description", "dry"),
        temperature_normal=bool(change.get("temperature_normal", True)),
        temperature_description=change.get("temperature_description", "warm"),
    )

    payload = _serialize_pulse(created)
    payload["action"] = "updated"
    emit_runtime_event(
        session=session,
        event_type="trainerlab.pulse.updated",
        payload=payload,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.pulse.updated:{created.id}",
    )


def _apply_intervention_effect(
    *,
    session: TrainerSession,
    change: dict[str, Any],
    state: dict[str, Any],
    correlation_id: str | None,
) -> None:
    target_id = change.get("intervention_event_id")
    if not target_id:
        return
    intervention = Intervention.objects.filter(
        simulation=session.simulation,
        pk=target_id,
    ).first()
    if intervention is None:
        return

    effects = dict(state.get("intervention_effects") or {})
    effects[str(intervention.id)] = {
        "status": change.get("status", "active"),
        "clinical_effect": change.get("clinical_effect", ""),
        "notes": change.get("notes", ""),
    }
    state["intervention_effects"] = effects

    emit_runtime_event(
        session=session,
        event_type="intervention.created",
        payload={
            "domain_event_id": intervention.id,
            "intervention_type": intervention.intervention_type or None,
            "site_code": intervention.site_code or None,
            "status": intervention.status,
            "effectiveness": intervention.effectiveness,
            "notes": intervention.notes,
            "supersedes_event_id": intervention.supersedes_id,
            "code": intervention.code,
            "description": intervention.description,
            "target": intervention.target,
            "anatomic_location": intervention.anatomic_location,
            "performed_by_role": intervention.performed_by_role,
            "effect": effects[str(intervention.id)],
        },
        correlation_id=correlation_id,
        idempotency_key=f"intervention.created:{intervention.id}:{effects[str(intervention.id)]['status']}",
    )

    # #6: Emit structured assessment event so clients get a closed-loop feedback signal
    assessed_status = change.get("status", "active")
    assessed_effectiveness = change.get("clinical_effect", "")
    emit_intervention_assessed(
        session=session,
        intervention_id=intervention.id,
        effectiveness=change.get("effectiveness", "unknown"),
        clinical_effect=assessed_effectiveness,
        status=assessed_status,
        correlation_id=correlation_id,
    )


def apply_runtime_turn_output(
    *,
    session_id: int,
    output_payload: dict[str, Any],
    service_context: dict[str, Any],
) -> dict[str, Any]:
    correlation_id = service_context.get("correlation_id")
    with transaction.atomic():
        session = (
            TrainerSession.objects.select_for_update()
            .select_related("simulation")
            .get(pk=session_id)
        )
        state = get_runtime_state(session)
        if session.status in TERMINAL_SESSION_STATUSES:
            state, _discarded = discard_runtime_work(state)
            session.runtime_state_json = state
            session.save(update_fields=["runtime_state_json", "modified_at"])
            return state
        processed_reasons = list(state.get("currently_processing_reasons") or [])

        for change in output_payload.get("state_changes", {}).get("conditions", []):
            _apply_condition_change(
                session=session,
                change=change,
                correlation_id=correlation_id,
            )

        for change in output_payload.get("state_changes", {}).get("vitals", []):
            _apply_vital_change(
                session=session,
                change=change,
                correlation_id=correlation_id,
            )

        for change in output_payload.get("state_changes", {}).get("pulses", []):
            _apply_pulse_change(
                session=session,
                change=change,
                correlation_id=correlation_id,
            )

        for change in output_payload.get("state_changes", {}).get("interventions", []):
            _apply_intervention_effect(
                session=session,
                change=change,
                state=state,
                correlation_id=correlation_id,
            )

        snapshot = dict(output_payload.get("snapshot") or {})
        patient_status = dict(snapshot.get("patient_status") or {})
        state["runtime_processing"] = False
        state["currently_processing_reasons"] = []
        state["last_runtime_error"] = ""
        state["snapshot_annotations"] = {
            **dict(state.get("snapshot_annotations") or {}),
            "patient_status": patient_status,
        }
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])

        refreshed = refresh_runtime_projection(
            session=session,
            correlation_id=correlation_id,
            ai_plan=dict(output_payload.get("instructor_intent") or {}),
            rationale_notes=list(output_payload.get("rationale_notes") or []),
            snapshot_annotations={"patient_status": patient_status},
            processed_reasons=processed_reasons,
            update_tick_timestamp=True,
        )

    if refreshed.get("pending_runtime_reasons"):
        _schedule_runtime_turn(session_id)

    return refreshed


def refresh_projection_from_domain_state(
    *,
    simulation_id: int,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    session = (
        TrainerSession.objects.select_related("simulation")
        .filter(simulation_id=simulation_id)
        .first()
    )
    if session is None:
        return {}
    return refresh_runtime_projection(session=session, correlation_id=correlation_id)


def enqueue_summary_debrief(*, session: TrainerSession) -> str | None:
    from .orca.services import GenerateTrainerRunDebrief

    try:
        return GenerateTrainerRunDebrief.task.using(
            context={
                "simulation_id": session.simulation_id,
                "session_id": session.id,
            },
        ).enqueue(
            user_message="Create the end-of-run TrainerLab debrief for the instructor.",
        )
    except Exception:
        logger.exception("trainerlab.summary.enqueue_failed", session_id=session.id)
        return None


def apply_debrief_output(
    *,
    session_id: int,
    output_payload: dict[str, Any],
    correlation_id: str | None = None,
) -> TrainerRunSummary:
    with transaction.atomic():
        session = (
            TrainerSession.objects.select_for_update()
            .select_related("simulation")
            .get(pk=session_id)
        )
        existing_summary_json = dict(
            getattr(getattr(session, "summary", None), "summary_json", {}) or {}
        )
        next_revision = int(existing_summary_json.get("ai_debrief_revision", 0) or 0) + 1
        summary, _ = TrainerRunSummary.objects.select_for_update().update_or_create(
            session=session,
            defaults={
                "summary_json": {
                    **existing_summary_json,
                    "ai_debrief": output_payload,
                    "ai_debrief_revision": next_revision,
                    "status": session.status,
                    "simulation_id": session.simulation_id,
                    "final_state": session.runtime_state_json,
                },
                "generator_version": "v2",
            },
        )

        state = get_runtime_state(session)
        state["summary_feedback"] = output_payload
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])

        emit_runtime_event(
            session=session,
            event_type="summary.updated",
            payload={
                "summary_id": summary.id,
                "ai_debrief": output_payload,
                "ai_debrief_revision": next_revision,
            },
            correlation_id=correlation_id,
            idempotency_key=f"summary.updated:{session.id}:{next_revision}",
        )
        return summary


def start_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.SEEDED:
        raise ValidationError("Session can only be started from seeded state")

    now = timezone.now()
    state = _set_active_elapsed_anchor(session, state=get_runtime_state(session), now=now)

    session.status = SessionStatus.RUNNING
    session.run_started_at = session.run_started_at or now
    session.run_paused_at = None
    session.tick_nonce += 1
    session.runtime_state_json = state
    session.save(
        update_fields=[
            "status",
            "run_started_at",
            "run_paused_at",
            "tick_nonce",
            "runtime_state_json",
            "modified_at",
        ]
    )

    emit_runtime_event(
        session=session,
        event_type="run.started",
        payload={"status": session.status},
        created_by=user,
        correlation_id=correlation_id,
    )
    append_pending_runtime_reason(
        session=session,
        reason_kind="run_started",
        payload={"status": session.status},
        correlation_id=correlation_id,
    )
    _schedule_tick(session)
    return session


def pause_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.RUNNING:
        raise ValidationError("Session can only be paused from running state")

    now = timezone.now()
    state = _freeze_active_elapsed(session, state=get_runtime_state(session), now=now)

    session.status = SessionStatus.PAUSED
    session.run_paused_at = now
    session.runtime_state_json = state
    session.save(update_fields=["status", "run_paused_at", "runtime_state_json", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="run.paused",
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

    now = timezone.now()
    state = _set_active_elapsed_anchor(session, state=get_runtime_state(session), now=now)

    session.status = SessionStatus.RUNNING
    session.run_paused_at = None
    session.tick_nonce += 1
    session.runtime_state_json = state
    session.save(
        update_fields=["status", "run_paused_at", "tick_nonce", "runtime_state_json", "modified_at"]
    )

    emit_runtime_event(
        session=session,
        event_type="run.resumed",
        payload={"status": session.status},
        created_by=user,
        correlation_id=correlation_id,
    )
    append_pending_runtime_reason(
        session=session,
        reason_kind="run_resumed",
        payload={"status": session.status},
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
    state = _freeze_active_elapsed(session, state=get_runtime_state(session), now=terminal_at)
    state, discarded_reasons = discard_runtime_work(state, discarded_at=terminal_at)

    session.status = SessionStatus.COMPLETED
    session.run_completed_at = terminal_at
    session.runtime_state_json = state
    session.save(update_fields=["status", "run_completed_at", "runtime_state_json", "modified_at"])

    if not session.simulation.is_complete:
        session.simulation.mark_completed()

    emit_runtime_event(
        session=session,
        event_type="run.stopped",
        payload={
            "status": session.status,
            "discarded_runtime_reason_count": len(discarded_reasons),
        },
        created_by=user,
        correlation_id=correlation_id,
    )
    build_summary(session=session, generated_by=user)
    enqueue_summary_debrief(session=session)
    return session


@transaction.atomic
def build_summary(*, session: TrainerSession, generated_by=None) -> TrainerRunSummary:
    events = list(session.runtime_events.order_by("created_at"))
    commands = list(session.commands.order_by("issued_at"))
    existing_summary_json = dict(
        getattr(getattr(session, "summary", None), "summary_json", {}) or {}
    )
    notes = list(
        SimulationNote.objects.filter(simulation=session.simulation).order_by("timestamp", "id")
    )

    summary_payload = {
        "session_id": session.id,
        "simulation_id": session.simulation_id,
        "status": session.status,
        "run_started_at": _iso_or_none(session.run_started_at),
        "run_completed_at": _iso_or_none(session.run_completed_at),
        "final_state": session.runtime_state_json,
        "event_type_counts": dict(Counter(event.event_type for event in events)),
        "timeline_highlights": [
            {
                "event_type": event.event_type,
                "created_at": _iso_or_none(event.created_at),
                "payload": event.payload,
            }
            for event in events[-10:]
        ],
        "notes": [
            {
                "note_id": note.id,
                "content": note.content,
                "source": note.source,
                "created_at": _iso_or_none(note.timestamp),
            }
            for note in notes
        ],
        "command_log": [
            {
                "id": str(command.id),
                "command_type": command.command_type,
                "status": command.status,
                "issued_at": _iso_or_none(command.issued_at),
                "payload": command.payload_json,
            }
            for command in commands
        ],
        "ai_rationale_notes": list(
            (session.runtime_state_json or {}).get("ai_rationale_notes", [])
        ),
        "ai_debrief": existing_summary_json.get("ai_debrief"),
        "ai_debrief_revision": int(existing_summary_json.get("ai_debrief_revision", 0) or 0),
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
        event_type="summary.ready",
        payload={"summary_id": summary.id},
        created_by=generated_by,
        idempotency_key=f"summary.ready:{summary.id}",
    )

    return summary


def refresh_completed_run_review(
    *, session: TrainerSession, generated_by=None
) -> TrainerRunSummary | None:
    if session.status != SessionStatus.COMPLETED:
        return None
    summary = build_summary(session=session, generated_by=generated_by)
    enqueue_summary_debrief(session=session)
    return summary


# ---------------------------------------------------------------------------
# #1 — Orca Pulse Vitals Service helpers
# ---------------------------------------------------------------------------


def apply_vitals_progression_output(
    *,
    session_id: int,
    output_payload: dict[str, Any],
    service_context: dict[str, Any],
) -> dict[str, Any]:
    """Persist vitals-only AI output and refresh runtime state."""
    correlation_id = service_context.get("correlation_id")
    with transaction.atomic():
        session = (
            TrainerSession.objects.select_for_update()
            .select_related("simulation")
            .get(pk=session_id)
        )
        state = get_runtime_state(session)
        if session.status in TERMINAL_SESSION_STATUSES:
            return state

        for change in output_payload.get("vitals", []):
            _apply_vital_change(session=session, change=change, correlation_id=correlation_id)

        refreshed = refresh_runtime_projection(
            session=session,
            correlation_id=correlation_id,
            update_tick_timestamp=False,
        )

    return refreshed


def enqueue_vitals_progression(
    *,
    session: TrainerSession,
    correlation_id: str | None = None,
) -> str | None:
    """Enqueue a vitals-only AI progression turn."""
    from .orca.services import GenerateVitalsProgression

    state = get_runtime_state(session)
    current_snapshot = project_current_snapshot(session, state=state)

    try:
        return GenerateVitalsProgression.task.using(
            context={
                "simulation_id": session.simulation_id,
                "session_id": session.id,
                "active_elapsed_seconds": get_active_elapsed_seconds(session, state=state),
                "current_snapshot": current_snapshot,
                "runtime_reasons": [{"reason_kind": "manual_vitals_tick"}],
                "correlation_id": correlation_id,
            },
        ).enqueue(
            user_message="Update the patient's vital signs based on current clinical state.",
        )
    except Exception:
        logger.exception("trainerlab.vitals.enqueue_failed", session_id=session.id)
        return None


# ---------------------------------------------------------------------------
# #2 — Condition control state mutation
# ---------------------------------------------------------------------------


def update_condition_control_state(
    *,
    session: TrainerSession,
    condition_id: int,
    kind: str,
    is_treated: bool | None = None,
    is_resolved: bool | None = None,
    correlation_id: str | None = None,
) -> Injury | Illness:
    """
    Update the instructor-controlled treatment/resolution state of an Injury or Illness.

    Creates a superseding event record (immutable event log) and deactivates the old one
    so the full condition history is preserved.
    """
    # Use kind to do a direct typed lookup — avoids PK collisions between the
    # independent auto-increment sequences on Injury and Illness tables.
    model_cls = Injury if kind == "injury" else Illness
    original: Injury | Illness | None = model_cls.objects.filter(
        pk=condition_id, simulation=session.simulation, is_active=True
    ).first()
    if original is None:
        raise ValidationError(f"Active condition {condition_id} not found for this simulation.")

    _deactivate_event(original)

    if isinstance(original, Injury):
        created: Injury | Illness = Injury.objects.create(
            simulation=session.simulation,
            source=EventSource.INSTRUCTOR,
            supersedes=original,
            injury_category=original.injury_category,
            injury_location=original.injury_location,
            injury_kind=original.injury_kind,
            injury_description=original.injury_description,
            parent_injury=original.parent_injury,
            is_treated=is_treated if is_treated is not None else original.is_treated,
            is_resolved=is_resolved if is_resolved is not None else original.is_resolved,
        )
    else:
        created = Illness.objects.create(
            simulation=session.simulation,
            source=EventSource.INSTRUCTOR,
            supersedes=original,
            name=original.name,
            description=original.description,
            severity=original.severity,
            is_resolved=is_resolved if is_resolved is not None else original.is_resolved,
        )

    is_treated_val = getattr(created, "is_treated", False)
    is_resolved_val = getattr(created, "is_resolved", False)
    if is_resolved_val:
        control_state = "resolved"
    elif is_treated_val:
        control_state = "controlled"
    else:
        control_state = "uncontrolled"

    payload = _serialize_condition(created)
    payload["control_state"] = control_state
    payload["action"] = "control_state_updated"

    emit_runtime_event(
        session=session,
        event_type="trainerlab.condition.control_state_updated",
        payload=payload,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.condition.control_state_updated:{created.id}",
    )

    refresh_runtime_projection(session=session, correlation_id=correlation_id)
    return created


# ---------------------------------------------------------------------------
# #3 — Manual tick trigger
# ---------------------------------------------------------------------------


def trigger_manual_tick(
    *,
    session: TrainerSession,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Immediately append a manual tick reason and schedule the runtime turn.

    Returns the queued reason dict.
    """
    if session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED}:
        raise ValidationError("Manual tick is only allowed on running or paused sessions.")

    reason = append_pending_runtime_reason(
        session=session,
        reason_kind="manual_tick",
        payload={"triggered_at": timezone.now().astimezone(UTC).isoformat()},
        correlation_id=correlation_id,
    )

    emit_runtime_event(
        session=session,
        event_type="trainerlab.tick.triggered",
        payload={
            "trigger": "manual",
            "correlation_id": correlation_id,
        },
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.tick.triggered:{session.id}:{reason['created_at']}",
    )
    return reason


# ---------------------------------------------------------------------------
# #4 — Live debrief annotations
# ---------------------------------------------------------------------------


def create_debrief_annotation(
    *,
    session: TrainerSession,
    created_by,
    learning_objective: str,
    observation_text: str,
    outcome: str,
    linked_event_id: int | None = None,
    elapsed_seconds_at: int | None = None,
    correlation_id: str | None = None,
) -> DebriefAnnotation:
    """Create a structured debrief annotation for this session."""
    annotation = DebriefAnnotation.objects.create(
        session=session,
        simulation=session.simulation,
        created_by=created_by,
        learning_objective=learning_objective,
        observation_text=observation_text,
        outcome=outcome,
        linked_event_id=linked_event_id,
        elapsed_seconds_at=elapsed_seconds_at,
    )
    emit_runtime_event(
        session=session,
        event_type="trainerlab.annotation.created",
        payload={
            "annotation_id": annotation.id,
            "learning_objective": annotation.learning_objective,
            "observation_text": annotation.observation_text,
            "outcome": annotation.outcome,
            "linked_event_id": annotation.linked_event_id,
            "elapsed_seconds_at": annotation.elapsed_seconds_at,
        },
        created_by=created_by,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.annotation.created:{annotation.id}",
    )
    return annotation


def get_session_annotations(*, session: TrainerSession) -> list[DebriefAnnotation]:
    return list(session.debrief_annotations.select_related("created_by").order_by("created_at"))


# ---------------------------------------------------------------------------
# #5 — Preset application diff
# ---------------------------------------------------------------------------


def snapshot_before_preset(session: TrainerSession) -> dict[str, Any]:
    """Capture a lightweight snapshot of active conditions and vitals before preset application."""
    state = get_runtime_state(session)
    conditions = []
    for model in (Injury, Illness):
        for obj in model.objects.filter(simulation=session.simulation, is_active=True):
            conditions.append(
                {
                    "id": obj.id,
                    "kind": "illness" if isinstance(obj, Illness) else "injury",
                    "label": getattr(obj, "name", None) or getattr(obj, "injury_description", ""),
                }
            )
    vitals = {}
    for vital_type, model in VITAL_TYPE_MODEL_MAP.items():
        obj = (
            model.objects.filter(simulation=session.simulation, is_active=True)
            .order_by("-timestamp", "-id")
            .first()
        )
        if obj is not None:
            vitals[vital_type] = {
                "min_value": obj.min_value,
                "max_value": obj.max_value,
            }
    return {
        "conditions": conditions,
        "vitals": vitals,
        "state_revision": int(state.get("state_revision", 0)),
    }


def compute_preset_diff(
    *,
    before: dict[str, Any],
    session: TrainerSession,
) -> dict[str, Any]:
    """Compare before/after snapshots and build a human-readable diff."""
    after_conditions = []
    for model in (Injury, Illness):
        for obj in model.objects.filter(simulation=session.simulation, is_active=True):
            after_conditions.append(
                {
                    "id": obj.id,
                    "kind": "illness" if isinstance(obj, Illness) else "injury",
                    "label": getattr(obj, "name", None) or getattr(obj, "injury_description", ""),
                }
            )
    before_ids = {c["id"] for c in before.get("conditions", [])}
    added_conditions = [c for c in after_conditions if c["id"] not in before_ids]

    after_vitals: dict[str, Any] = {}
    for vital_type, model in VITAL_TYPE_MODEL_MAP.items():
        obj = (
            model.objects.filter(simulation=session.simulation, is_active=True)
            .order_by("-timestamp", "-id")
            .first()
        )
        if obj is not None:
            after_vitals[vital_type] = {
                "min_value": obj.min_value,
                "max_value": obj.max_value,
            }

    changed_vitals: dict[str, Any] = {}
    for vtype, after_val in after_vitals.items():
        before_val = before.get("vitals", {}).get(vtype)
        if before_val != after_val:
            changed_vitals[vtype] = {"before": before_val, "after": after_val}

    return {
        "conditions_added": added_conditions,
        "vitals_changed": changed_vitals,
        "state_revision_before": before.get("state_revision"),
    }


# ---------------------------------------------------------------------------
# #6 — Intervention assessed event (called from _apply_intervention_effect)
# ---------------------------------------------------------------------------


def emit_intervention_assessed(
    *,
    session: TrainerSession,
    intervention_id: int,
    effectiveness: str,
    clinical_effect: str,
    status: str,
    correlation_id: str | None = None,
) -> None:
    """Emit trainerlab.intervention.assessed when the AI evaluates an intervention."""
    intervention = Intervention.objects.filter(
        pk=intervention_id,
        simulation=session.simulation,
    ).first()
    if intervention is None:
        return

    target_condition_id: int | None = None
    target_condition_label: str | None = None
    target_condition_control_state: str | None = None
    if intervention.target_problem_id:
        problem = Problem.objects.filter(pk=intervention.target_problem_id).first()
        if problem:
            target_condition_id = problem.pk
            # Derive label from the underlying cause (Injury/Illness)
            cause = problem.cause
            if cause:
                injury = Injury.objects.filter(pk=cause.pk).first()
                if injury:
                    target_condition_label = injury.injury_description
            if problem.is_resolved:
                target_condition_control_state = "resolved"
            elif problem.is_treated:
                target_condition_control_state = "controlled"
            else:
                target_condition_control_state = "uncontrolled"

    emit_runtime_event(
        session=session,
        event_type="trainerlab.intervention.assessed",
        payload={
            "intervention_id": intervention_id,
            "intervention_type": intervention.intervention_type or None,
            "site_code": intervention.site_code or None,
            "effectiveness": effectiveness,
            "clinical_effect": clinical_effect,
            "status": status,
            "target_condition_id": target_condition_id,
            "target_condition_label": target_condition_label,
            "target_condition_control_state": target_condition_control_state,
        },
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.intervention.assessed:{intervention_id}:{status}",
    )


# ---------------------------------------------------------------------------
# #7 — Scenario brief edit
# ---------------------------------------------------------------------------


def update_scenario_brief(
    *,
    session: TrainerSession,
    updates: dict[str, Any],
    user=None,
    correlation_id: str | None = None,
) -> ScenarioBrief:
    """
    Edit the scenario brief text fields.

    Creates a new superseding ScenarioBrief event and updates runtime_state_json.
    """
    existing = (
        ScenarioBrief.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    if existing is not None:
        _deactivate_event(existing)

    current_brief: dict[str, Any] = {}
    if existing is not None:
        current_brief = {
            "read_aloud_brief": existing.read_aloud_brief,
            "environment": existing.environment,
            "location_overview": existing.location_overview,
            "threat_context": existing.threat_context,
            "evacuation_options": existing.evacuation_options,
            "evacuation_time": existing.evacuation_time,
            "special_considerations": existing.special_considerations,
        }

    merged = {**current_brief, **{k: v for k, v in updates.items() if v is not None}}
    new_brief = ScenarioBrief.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=existing,
        read_aloud_brief=merged.get("read_aloud_brief", ""),
        environment=merged.get("environment", ""),
        location_overview=merged.get("location_overview", ""),
        threat_context=merged.get("threat_context", ""),
        evacuation_options=merged.get("evacuation_options", []),
        evacuation_time=merged.get("evacuation_time", ""),
        special_considerations=merged.get("special_considerations", []),
    )

    state = get_runtime_state(session)
    state["scenario_brief"] = {
        "read_aloud_brief": new_brief.read_aloud_brief,
        "environment": new_brief.environment,
        "location_overview": new_brief.location_overview,
        "threat_context": new_brief.threat_context,
        "evacuation_options": new_brief.evacuation_options,
        "evacuation_time": new_brief.evacuation_time,
        "special_considerations": new_brief.special_considerations,
    }
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.scenario_brief.updated",
        payload={
            "domain_event_id": new_brief.id,
            "read_aloud_brief": new_brief.read_aloud_brief,
            "environment": new_brief.environment,
            "location_overview": new_brief.location_overview,
            "threat_context": new_brief.threat_context,
            "evacuation_options": new_brief.evacuation_options,
            "evacuation_time": new_brief.evacuation_time,
            "special_considerations": new_brief.special_considerations,
        },
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.scenario_brief.updated:{new_brief.id}",
    )
    return new_brief
