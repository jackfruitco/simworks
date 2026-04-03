from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from asgiref.sync import async_to_sync
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.outbox import enqueue_event_sync, event_types as outbox_events, poke_drain_sync
from apps.common.retries import has_user_retries_remaining
from apps.simcore.models import Simulation
from apps.simcore.utils import generate_fake_name
from config.logging import get_logger
from orchestrai_django.models import ServiceCall as ServiceCallModel

from .event_payloads import (
    serialize_domain_event,
    serialize_intervention_summary,
    serialize_problem_snapshot,
    serialize_recommendation_summary,
)
from .finding_dictionary import get_finding_definition
from .models import (
    ETCO2,
    SPO2,
    AssessmentFinding,
    BloodGlucoseLevel,
    BloodPressure,
    DebriefAnnotation,
    DiagnosticResult,
    DispositionState,
    EventSource,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    PatientStatusState,
    Problem,
    PulseAssessment,
    RecommendationEvaluation,
    RecommendedIntervention,
    ResourceState,
    RespiratoryRate,
    RuntimeEvent,
    ScenarioBrief,
    SessionStatus,
    SimulationNote,
    TrainerAgentViewModelRecord,
    TrainerCommand,
    TrainerRunSummary,
    TrainerSession,
)
from .problem_dictionary import get_problem_definition, normalize_problem_kind
from .recommendations import (
    generate_rule_based_recommendations,
    validate_and_normalize_recommendation,
)
from .runtime_llm import (
    enforce_runtime_token_budget,
    get_runtime_max_batch_reasons,
    get_runtime_max_output_tokens,
    get_runtime_max_prompt_tokens,
)
from .schemas.shared import RuntimePatientStatus
from .viewmodels import (
    BUILDER_VERSION as VIEWMODEL_BUILDER_VERSION,
    SCHEMA_VERSION as VIEWMODEL_SCHEMA_VERSION,
    build_scenario_snapshot,
    build_trainer_agent_view_model,
    build_trainer_derived_views,
    build_trainer_rest_view_model,
    load_trainer_engine_aggregate,
)

MIN_TICK_INTERVAL = 5
MAX_TICK_INTERVAL = 60
DEFAULT_TICK_INTERVAL = 15
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
    phase: str = "seeded",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = {
        "phase": phase,
        "last_instruction": directives,
        "tick_count": 0,
        "state_revision": 0,
        "initial_generation_retryable": None,
        "active_elapsed_seconds": 0,
        "active_elapsed_anchor_started_at": None,
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
        "llm_conditions_check": [],
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
        "control_plane_debug": {
            "execution_plan": ["core_runtime", "vitals", "recommendation", "narrative"],
            "current_step_index": 0,
            "queued_reasons": [],
            "currently_processing_reasons": [],
            "last_processed_reasons": [],
            "last_request_profile": {},
            "last_failed_step": "",
            "last_failed_error": "",
            "last_patch_evaluation": {},
            "last_rejected_or_normalized": {},
            "status_flags": {"runtime_processing": False},
        },
    }
    merged = dict(baseline)
    if state:
        merged.update(state)
        merged["ai_plan"] = {
            **baseline["ai_plan"],
            **dict(state.get("ai_plan") or {}),
        }
    return merged


def record_patch_evaluation_summary(
    *,
    session: TrainerSession,
    correlation_id: str | None,
    summary: dict[str, Any],
) -> None:
    state = get_runtime_state(session)
    debug = dict(state.get("control_plane_debug") or {})
    debug["last_patch_evaluation"] = summary
    if summary.get("rejected") or summary.get("normalized"):
        debug["last_rejected_or_normalized"] = {
            "rejected": summary.get("rejected", []),
            "normalized": summary.get("normalized", []),
        }
    debug["status_flags"] = {
        **dict(debug.get("status_flags") or {}),
        "runtime_processing": bool(state.get("runtime_processing")),
    }
    state["control_plane_debug"] = debug
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])
    emit_runtime_event(
        session=session,
        event_type=outbox_events.SIMULATION_PATCH_EVALUATION_COMPLETED,
        payload=summary,
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.SIMULATION_PATCH_EVALUATION_COMPLETED}:"
            f"{session.id}:{state.get('state_revision', 0)}"
        ),
    )


def get_runtime_state(session: TrainerSession) -> dict[str, Any]:
    return build_runtime_state_defaults(
        directives=session.initial_directives or "",
        state=dict(session.runtime_state_json or {}),
    )


def _log_deprecated_snapshot_wrapper(name: str, *, session: TrainerSession) -> None:
    logger.warning(
        f"trainerlab.deprecated.{name}",
        session_id=session.id,
        simulation_id=session.simulation_id,
    )


def _current_patient_status_payload(session: TrainerSession) -> dict[str, Any]:
    existing = (
        PatientStatusState.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    if existing is None:
        return {}
    return {
        "avpu": existing.avpu or None,
        "respiratory_distress": existing.respiratory_distress,
        "hemodynamic_instability": existing.hemodynamic_instability,
        "impending_pneumothorax": existing.impending_pneumothorax,
        "tension_pneumothorax": existing.tension_pneumothorax,
    }


def _derive_patient_status_truth(
    *,
    session: TrainerSession,
    base_status: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_payload = RuntimePatientStatus.model_validate(base_status or {})
    active_problems = list(
        Problem.objects.filter(simulation=session.simulation, is_active=True).order_by(
            "timestamp", "id"
        )
    )
    active_kinds = {problem.kind for problem in active_problems}
    return {
        "avpu": normalized_payload.avpu or None,
        "respiratory_distress": bool(
            normalized_payload.respiratory_distress
            or {"respiratory_distress", "tension_pneumothorax", "hypoxia"} & active_kinds
        ),
        "hemodynamic_instability": bool(
            normalized_payload.hemodynamic_instability
            or {"hemorrhage", "hypoperfusion_shock"} & active_kinds
        ),
        "tension_pneumothorax": bool(
            normalized_payload.tension_pneumothorax or "tension_pneumothorax" in active_kinds
        ),
        "impending_pneumothorax": bool(
            normalized_payload.impending_pneumothorax
            or ("open_chest_wound" in active_kinds and "tension_pneumothorax" not in active_kinds)
        ),
    }


def _persist_patient_status_state(
    *,
    session: TrainerSession,
    base_status: dict[str, Any] | None,
    source: str = EventSource.SYSTEM,
) -> PatientStatusState:
    normalized_payload = _derive_patient_status_truth(session=session, base_status=base_status)
    existing = (
        PatientStatusState.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    if existing is not None:
        existing_payload = {
            "avpu": existing.avpu or None,
            "respiratory_distress": existing.respiratory_distress,
            "hemodynamic_instability": existing.hemodynamic_instability,
            "impending_pneumothorax": existing.impending_pneumothorax,
            "tension_pneumothorax": existing.tension_pneumothorax,
        }
        if existing_payload == normalized_payload:
            return existing
        _deactivate_event(existing)

    patient_status = PatientStatusState.objects.create(
        simulation=session.simulation,
        source=source,
        supersedes=existing,
        avpu=normalized_payload.get("avpu") or "",
        respiratory_distress=bool(normalized_payload.get("respiratory_distress")),
        hemodynamic_instability=bool(normalized_payload.get("hemodynamic_instability")),
        impending_pneumothorax=bool(normalized_payload.get("impending_pneumothorax")),
        tension_pneumothorax=bool(normalized_payload.get("tension_pneumothorax")),
    )
    logger.info(
        "trainerlab.scenario_state.patient_status.updated",
        session_id=session.id,
        simulation_id=session.simulation_id,
        patient_status_state_id=patient_status.id,
        source=source,
    )
    return patient_status


def _build_scenario_snapshot_for_session(
    session: TrainerSession,
    *,
    event_limit: int = 100,
    runtime_state_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aggregate = load_trainer_engine_aggregate(
        session=session,
        event_limit=event_limit,
        runtime_state_override=runtime_state_override,
    )
    snapshot = build_scenario_snapshot(aggregate)
    return snapshot.model_dump(mode="json")


def _persist_runtime_state_and_load_aggregate(
    *,
    session: TrainerSession,
    state: dict[str, Any],
    now: datetime,
    update_tick_timestamp: bool,
):
    session.runtime_state_json = state
    update_fields = ["runtime_state_json", "modified_at"]
    if update_tick_timestamp:
        session.last_ai_tick_at = now
        update_fields.append("last_ai_tick_at")
    session.save(update_fields=update_fields)
    return load_trainer_engine_aggregate(
        session=session,
        runtime_state_override=state,
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


def emit_domain_runtime_event(
    *,
    session: TrainerSession,
    event_type: str,
    obj: Any,
    extra: dict[str, Any] | None = None,
    created_by=None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
) -> RuntimeEvent:
    """Emit a domain-centric event payload from a concrete TrainerLab state object."""
    return emit_runtime_event(
        session=session,
        event_type=event_type,
        payload=serialize_domain_event(obj, extra=extra),
        created_by=created_by,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )


def emit_simulation_status_event(
    *,
    session: TrainerSession,
    previous_status: str | None,
    created_by=None,
    correlation_id: str | None = None,
    retryable: bool | None = None,
    idempotency_key: str | None = None,
    extra: dict[str, Any] | None = None,
) -> RuntimeEvent:
    state = get_runtime_state(session)
    payload = {
        "simulation_id": session.simulation_id,
        "session_id": session.id,
        "status": session.status,
        "phase": state.get("phase"),
    }
    if previous_status is not None:
        payload["from"] = previous_status
        payload["to"] = session.status
    if retryable is not None:
        payload["retryable"] = retryable
    if extra:
        payload.update(extra)
    return emit_runtime_event(
        session=session,
        event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        payload=payload,
        created_by=created_by,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )


def _domain_deactivation_event_type(obj: Any) -> str | None:
    if isinstance(obj, Injury):
        return outbox_events.PATIENT_INJURY_UPDATED
    if isinstance(obj, Illness):
        return outbox_events.PATIENT_ILLNESS_UPDATED
    if isinstance(obj, Problem):
        return outbox_events.PATIENT_PROBLEM_UPDATED
    if isinstance(obj, RecommendedIntervention):
        return outbox_events.PATIENT_RECOMMENDED_INTERVENTION_REMOVED
    if isinstance(obj, AssessmentFinding):
        return outbox_events.PATIENT_ASSESSMENT_FINDING_REMOVED
    if isinstance(obj, DiagnosticResult):
        return outbox_events.PATIENT_DIAGNOSTIC_RESULT_UPDATED
    if isinstance(obj, ResourceState):
        return outbox_events.PATIENT_RESOURCE_UPDATED
    if isinstance(obj, DispositionState):
        return outbox_events.PATIENT_DISPOSITION_UPDATED
    if isinstance(obj, Intervention):
        return outbox_events.PATIENT_INTERVENTION_UPDATED
    return None


def deactivate_domain_object(
    *,
    session: TrainerSession,
    obj: Any | None,
    correlation_id: str | None = None,
    created_by=None,
    action: str = "deactivated",
) -> None:
    if obj is None or not getattr(obj, "is_active", False):
        return
    obj.is_active = False
    obj.save(update_fields=["is_active"])
    if isinstance(obj, Problem | Injury | Illness):
        for recommendation in obj.recommended_interventions.filter(is_active=True):
            deactivate_domain_object(
                session=session,
                obj=recommendation,
                correlation_id=correlation_id,
                created_by=created_by,
                action="superseded",
            )
    event_type = _domain_deactivation_event_type(obj)
    if event_type is None:
        return
    emit_domain_runtime_event(
        session=session,
        event_type=event_type,
        obj=obj,
        extra={"action": action},
        created_by=created_by,
        correlation_id=correlation_id,
        idempotency_key=f"{event_type}:{type(obj).__name__.lower()}:{obj.id}:inactive",
    )


def _problem_control_state(problem: Problem) -> str:
    return problem.status


def _serialize_condition(problem: Problem, cause: Injury | Illness | None) -> dict[str, Any]:
    del cause
    return serialize_problem_snapshot(problem)


def _serialize_intervention(
    obj: Intervention,
    *,
    intervention_effects: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effect = dict((intervention_effects or {}).get(str(obj.id), {}))
    payload = serialize_intervention_summary(obj)
    payload["domain_event_id"] = obj.id
    payload["clinical_effect"] = effect.get("clinical_effect", "")
    return payload


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
    # TODO(trainerlab-refactor): remove this deprecated wrapper after all internal callers
    # have moved to build_scenario_snapshot(load_trainer_engine_aggregate(...)).
    _log_deprecated_snapshot_wrapper("project_current_snapshot", session=session)
    runtime_state = None
    if state is not None:
        runtime_state = build_runtime_state_defaults(
            directives=session.initial_directives or "",
            state=state,
        )
    return _build_scenario_snapshot_for_session(
        session,
        runtime_state_override=runtime_state,
    )


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
    # TODO(trainerlab-refactor): remove this deprecated wrapper after all internal callers
    # have moved to build_*_view_model(load_trainer_engine_aggregate(...)).
    # Transitional snapshot/update events are derived from the shared read model. Domain
    # events continue to be emitted from serialize_domain_event(...) payloads.
    _log_deprecated_snapshot_wrapper("refresh_runtime_projection", session=session)
    now = timezone.now()
    state = get_runtime_state(session)

    if snapshot_annotations is not None:
        logger.warning(
            "trainerlab.deprecated.refresh_runtime_projection.snapshot_annotations",
            session_id=session.id,
            simulation_id=session.simulation_id,
        )
        state["snapshot_annotations"] = dict(snapshot_annotations)
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
    state["state_revision"] = int(state.get("state_revision", 0) or 0) + 1
    state["last_runtime_completed_at"] = now.astimezone(UTC).isoformat()

    aggregate = _persist_runtime_state_and_load_aggregate(
        session=session,
        state=state,
        now=now,
        update_tick_timestamp=update_tick_timestamp,
    )
    derived_views = build_trainer_derived_views(aggregate)
    rest_view_model = build_trainer_rest_view_model(aggregate, derived_views=derived_views)
    runtime_snapshot = derived_views.runtime_snapshot.model_dump(mode="json")
    scenario_snapshot_payload = derived_views.scenario_snapshot.model_dump(mode="json")

    emit_runtime_event(
        session=session,
        event_type=outbox_events.SIMULATION_SNAPSHOT_UPDATED,
        payload={
            "simulation_id": rest_view_model.simulation_id,
            "session_id": rest_view_model.session_id,
            "status": rest_view_model.status,
            "scenario_snapshot": scenario_snapshot_payload,
            "runtime_snapshot": runtime_snapshot,
            "metadata": rest_view_model.metadata.model_dump(mode="json"),
            "processed_reasons": processed_reasons or [],
        },
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.SIMULATION_SNAPSHOT_UPDATED}:{session.id}:{state['state_revision']}"
        ),
    )

    emit_runtime_event(
        session=session,
        event_type=outbox_events.SIMULATION_PLAN_UPDATED,
        payload={
            "simulation_id": rest_view_model.simulation_id,
            "session_id": rest_view_model.session_id,
            "status": rest_view_model.status,
            "runtime_snapshot": runtime_snapshot,
            "ai_plan": runtime_snapshot["ai_plan"],
            "metadata": rest_view_model.metadata.model_dump(mode="json"),
        },
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.SIMULATION_PLAN_UPDATED}:{session.id}:{state['state_revision']}"
        ),
    )
    return state


def create_session(
    *,
    user,
    account=None,
    scenario_spec: dict[str, Any] | None,
    directives: str | None,
    modifiers: list[str] | None,
    status: str = SessionStatus.SEEDED,
    emit_seeded_event: bool = True,
    correlation_id: str | None = None,
) -> TrainerSession:
    scenario_spec = scenario_spec or {}
    modifiers = modifiers or []

    patient_name = async_to_sync(generate_fake_name)()
    diagnosis = scenario_spec.get("diagnosis")
    chief_complaint = scenario_spec.get("chief_complaint")

    simulation = Simulation.objects.create(
        user=user,
        account=account,
        sim_patient_full_name=patient_name,
        diagnosis=diagnosis,
        chief_complaint=chief_complaint,
    )

    initial_phase = "seeded" if status == SessionStatus.SEEDED else "seeding"
    initial_state = build_runtime_state_defaults(
        directives=directives or "",
        phase=initial_phase,
    )
    session = TrainerSession.objects.create(
        simulation=simulation,
        status=status,
        scenario_spec_json={**scenario_spec, "modifiers": modifiers},
        initial_directives=directives or "",
        runtime_state_json=initial_state,
        tick_interval_seconds=_normalize_tick_interval(scenario_spec.get("tick_interval_seconds")),
    )

    if status == SessionStatus.SEEDING:
        emit_simulation_status_event(
            session=session,
            previous_status=None,
            created_by=user,
            correlation_id=correlation_id,
            idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:seeding",
            extra={
                "scenario_spec": session.scenario_spec_json,
                "state_revision": initial_state["state_revision"],
            },
        )
    elif emit_seeded_event:
        emit_simulation_status_event(
            session=session,
            previous_status=None,
            created_by=user,
            correlation_id=correlation_id,
            idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:seeded",
            extra={
                "scenario_spec": session.scenario_spec_json,
                "state_revision": initial_state["state_revision"],
            },
        )

    return session


def _normalize_initial_generation_reason(reason_code: str | None) -> str:
    normalized = reason_code or "failed"
    if normalized.startswith("trainerlab_initial_generation_"):
        return normalized
    return f"trainerlab_initial_generation_{normalized}"


def _set_session_phase(
    session: TrainerSession,
    *,
    phase: str,
    error: str = "",
    initial_generation_retryable: bool | None = None,
) -> TrainerSession:
    state = get_runtime_state(session)
    state["phase"] = phase
    state["last_runtime_error"] = error
    state["initial_generation_retryable"] = initial_generation_retryable
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])
    return session


def fail_initial_scenario_generation(
    *,
    simulation_id: int,
    reason_code: str | None,
    reason_text: str,
    retryable: bool,
    correlation_id: str | None = None,
) -> TrainerSession | None:
    session = (
        TrainerSession.objects.select_related("simulation")
        .filter(simulation_id=simulation_id)
        .first()
    )
    if session is None:
        return None

    normalized_reason = _normalize_initial_generation_reason(reason_code)
    retryable = retryable and has_user_retries_remaining(session.simulation.initial_retry_count)
    _set_session_phase(
        session,
        phase="failed",
        error=reason_text,
        initial_generation_retryable=retryable,
    )
    session.status = SessionStatus.FAILED
    session.save(update_fields=["status", "modified_at"])
    session.simulation.mark_failed(
        reason_code=normalized_reason,
        reason_text=reason_text,
        retryable=retryable,
    )
    emit_simulation_status_event(
        session=session,
        previous_status=SessionStatus.SEEDING,
        correlation_id=correlation_id,
        retryable=retryable,
        idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:{normalized_reason}",
        extra={
            "reason_code": normalized_reason,
            "reason_text": reason_text,
        },
    )
    return session


def complete_initial_scenario_generation(
    *,
    simulation_id: int,
    correlation_id: str | None = None,
    call_id: str | None = None,
) -> TrainerSession | None:
    session = (
        TrainerSession.objects.select_related("simulation")
        .filter(simulation_id=simulation_id)
        .first()
    )
    if session is None:
        return None

    if session.status == SessionStatus.FAILED:
        logger.info(
            "Skipping TrainerLab initial-generation completion for failed simulation %s",
            simulation_id,
        )
        return session

    state = get_runtime_state(session)
    if session.status == SessionStatus.SEEDED and state.get("phase") == "seeded":
        return session

    state["phase"] = "seeded"
    state["last_runtime_error"] = ""
    state["initial_generation_retryable"] = None
    session.status = SessionStatus.SEEDED
    session.runtime_state_json = state
    session.save(update_fields=["status", "runtime_state_json", "modified_at"])

    emit_simulation_status_event(
        session=session,
        previous_status=SessionStatus.SEEDING,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:seeded",
        extra={
            "scenario_spec": session.scenario_spec_json,
            "state_revision": state["state_revision"],
            "call_id": call_id,
        },
    )

    _emit_seeded_vital_events(session)
    _emit_seeded_condition_events(session)
    _emit_seeded_pulse_events(session)
    return session


def is_initial_generation_retryable(session: TrainerSession) -> bool:
    reason_code = getattr(session.simulation, "terminal_reason_code", "") or ""
    if not reason_code.startswith("trainerlab_initial_generation_"):
        return False
    state = get_runtime_state(session)
    retryable = state.get("initial_generation_retryable")
    if retryable is None:
        retryable = True
    return bool(retryable) and has_user_retries_remaining(session.simulation.initial_retry_count)


def enqueue_initial_scenario_generation(
    *,
    session: TrainerSession,
    correlation_id: str | None = None,
    retryable: bool | None = None,
) -> str | None:
    from .orca.services import GenerateInitialScenario

    try:
        return GenerateInitialScenario.task.using(
            context={
                "simulation_id": session.simulation_id,
                "correlation_id": correlation_id,
            },
        ).enqueue(
            user_message="Generate the initial TrainerLab scenario state.",
        )
    except Exception:
        logger.exception(
            "Initial generation enqueue failed for simulation %s", session.simulation_id
        )
        fail_initial_scenario_generation(
            simulation_id=session.simulation_id,
            reason_code="trainerlab_initial_generation_enqueue_failed",
            reason_text="We could not start this simulation. Please try again.",
            retryable=True if retryable is None else retryable,
            correlation_id=correlation_id,
        )
        return None


def retry_initial_scenario_generation(
    *,
    session: TrainerSession,
    correlation_id: str | None = None,
) -> str | None:
    if session.status != SessionStatus.FAILED:
        raise ValidationError("Initial generation retry is only available for failed simulations")

    if not is_initial_generation_retryable(session):
        raise ValidationError("Initial generation retry is not available for this failure")

    session.simulation.initial_retry_count += 1
    session.simulation.save(update_fields=["initial_retry_count"])
    session.simulation.mark_in_progress()

    state = get_runtime_state(session)
    state["phase"] = "seeding"
    state["last_runtime_error"] = ""
    state["initial_generation_retryable"] = None
    state["currently_processing_reasons"] = []
    session.status = SessionStatus.SEEDING
    session.runtime_state_json = state
    session.save(update_fields=["status", "runtime_state_json", "modified_at"])

    retryable = has_user_retries_remaining(session.simulation.initial_retry_count)
    return enqueue_initial_scenario_generation(
        session=session,
        correlation_id=correlation_id,
        retryable=retryable,
    )


def create_session_with_initial_generation(
    *,
    user,
    account=None,
    scenario_spec: dict[str, Any] | None,
    directives: str | None,
    modifiers: list[str] | None,
    correlation_id: str | None = None,
) -> tuple[TrainerSession, str | None]:
    session = create_session(
        user=user,
        account=account,
        scenario_spec=scenario_spec,
        directives=directives,
        modifiers=modifiers,
        status=SessionStatus.SEEDING,
        emit_seeded_event=False,
        correlation_id=correlation_id,
    )
    call_id = enqueue_initial_scenario_generation(
        session=session,
        correlation_id=correlation_id,
    )
    if call_id is None:
        session.refresh_from_db()
    return session, call_id


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
                event_type=outbox_events.PATIENT_VITAL_CREATED,
                payload=_serialize_vital(vital_type, obj),
                idempotency_key=(
                    f"{outbox_events.PATIENT_VITAL_CREATED}:seeded:{session.id}:{vital_type}"
                ),
            )


def _emit_seeded_pulse_events(session: TrainerSession) -> None:
    for obj in PulseAssessment.objects.filter(
        simulation=session.simulation, is_active=True
    ).order_by("location"):
        emit_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_PULSE_CREATED,
            payload=_serialize_pulse(obj),
            idempotency_key=(
                f"{outbox_events.PATIENT_PULSE_CREATED}:seeded:{session.id}:{obj.location}"
            ),
        )


def _emit_seeded_condition_events(session: TrainerSession) -> None:
    scenario_brief = (
        ScenarioBrief.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    injuries = list(
        Injury.objects.filter(simulation=session.simulation, is_active=True).order_by(
            "timestamp", "id"
        )
    )
    illnesses = list(
        Illness.objects.filter(simulation=session.simulation, is_active=True).order_by(
            "timestamp", "id"
        )
    )
    problems = list(
        Problem.objects.select_related("cause_injury", "cause_illness")
        .prefetch_related("recommended_interventions")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    recommendations = list(
        RecommendedIntervention.objects.select_related(
            "target_problem",
            "target_injury",
            "target_illness",
        )
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    findings = list(
        AssessmentFinding.objects.select_related("target_problem")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    diagnostics = list(
        DiagnosticResult.objects.select_related("target_problem")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    resources = list(
        ResourceState.objects.filter(simulation=session.simulation, is_active=True).order_by(
            "timestamp", "id"
        )
    )
    disposition = (
        DispositionState.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    recommendation_evaluations = list(
        RecommendationEvaluation.objects.select_related("recommendation", "target_problem")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    if scenario_brief is not None:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.SIMULATION_BRIEF_CREATED,
            obj=scenario_brief,
            idempotency_key=(
                f"{outbox_events.SIMULATION_BRIEF_CREATED}:seeded:{session.id}:{scenario_brief.id}"
            ),
        )
    for injury in injuries:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_INJURY_CREATED,
            obj=injury,
            idempotency_key=f"{outbox_events.PATIENT_INJURY_CREATED}:seeded:{session.id}:{injury.id}",
        )
    for illness in illnesses:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_ILLNESS_CREATED,
            obj=illness,
            idempotency_key=f"{outbox_events.PATIENT_ILLNESS_CREATED}:seeded:{session.id}:{illness.id}",
        )
    for problem in problems:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_PROBLEM_CREATED,
            obj=problem,
            idempotency_key=f"{outbox_events.PATIENT_PROBLEM_CREATED}:seeded:{session.id}:{problem.id}",
        )
    for recommendation in recommendations:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_RECOMMENDED_INTERVENTION_CREATED,
            obj=recommendation,
            idempotency_key=(
                f"{outbox_events.PATIENT_RECOMMENDED_INTERVENTION_CREATED}:"
                f"seeded:{session.id}:{recommendation.id}"
            ),
        )
    for finding in findings:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_ASSESSMENT_FINDING_CREATED,
            obj=finding,
            idempotency_key=(
                f"{outbox_events.PATIENT_ASSESSMENT_FINDING_CREATED}:"
                f"seeded:{session.id}:{finding.id}"
            ),
        )
    for diagnostic in diagnostics:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_DIAGNOSTIC_RESULT_CREATED,
            obj=diagnostic,
            idempotency_key=(
                f"{outbox_events.PATIENT_DIAGNOSTIC_RESULT_CREATED}:"
                f"seeded:{session.id}:{diagnostic.id}"
            ),
        )
    for resource in resources:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_RESOURCE_UPDATED,
            obj=resource,
            idempotency_key=(
                f"{outbox_events.PATIENT_RESOURCE_UPDATED}:seeded:{session.id}:{resource.id}"
            ),
        )
    if disposition is not None:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_DISPOSITION_UPDATED,
            obj=disposition,
            idempotency_key=(
                f"{outbox_events.PATIENT_DISPOSITION_UPDATED}:seeded:{session.id}:{disposition.id}"
            ),
        )
    for evaluation in recommendation_evaluations:
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_RECOMMENDATION_EVALUATION_CREATED,
            obj=evaluation,
            idempotency_key=(
                f"{outbox_events.PATIENT_RECOMMENDATION_EVALUATION_CREATED}:"
                f"seeded:{session.id}:{evaluation.id}"
            ),
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


RUNTIME_TURN_USER_MESSAGE = (
    "Process the next TrainerLab runtime turn and return the authoritative patient update."
)


def _runtime_reason_priority(reason: dict[str, Any]) -> int:
    reason_kind = str(reason.get("reason_kind") or "")
    payload = dict(reason.get("payload") or {})
    if reason_kind.endswith("_recorded"):
        if reason_kind == "note_recorded":
            return 100 if payload.get("send_to_ai") else 80
        return 100
    if reason_kind in {"adjustment", "steer_prompt", "preset_applied"}:
        return 80
    if reason_kind in {"run_started", "run_resumed", "manual_tick"}:
        return 60
    if reason_kind == "tick":
        return 20
    return 40


def _select_runtime_batch_reasons(
    *,
    pending: list[dict[str, Any]],
    session_status: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_batch_reasons = get_runtime_max_batch_reasons()
    candidates: list[tuple[int, dict[str, Any]]] = []
    discarded_indices: set[int] = set()

    for index, reason in enumerate(pending):
        if session_status != SessionStatus.RUNNING and reason.get("reason_kind") == "tick":
            discarded_indices.add(index)
            continue
        candidates.append((index, reason))

    selected_indices = {
        index
        for index, _reason in sorted(
            candidates,
            key=lambda item: (-_runtime_reason_priority(item[1]), item[0]),
        )[:max_batch_reasons]
    }
    selected = [reason for index, reason in enumerate(pending) if index in selected_indices]
    remaining = [
        reason
        for index, reason in enumerate(pending)
        if index not in selected_indices and index not in discarded_indices
    ]
    return selected, remaining


def _update_runtime_request_profile(*, session_id: int, metrics: dict[str, Any]) -> None:
    metrics = _normalize_runtime_request_metrics(metrics)
    with transaction.atomic():
        session = TrainerSession.objects.select_for_update().get(pk=session_id)
        state = get_runtime_state(session)
        debug = dict(state.get("control_plane_debug") or {})
        debug["last_request_profile"] = dict(metrics)
        state["control_plane_debug"] = debug
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])


def _persist_runtime_request_metrics(*, call_id: str, metrics: dict[str, Any]) -> None:
    metrics = _normalize_runtime_request_metrics(metrics)
    with transaction.atomic():
        call = ServiceCallModel.objects.select_for_update().get(pk=call_id)
        context = dict(call.context or {})
        context["runtime_request_metrics"] = dict(metrics)
        call.context = context
        call.save(update_fields=["context"])


def _persist_trainer_agent_view_model_record(
    *,
    session_id: int,
    state_revision: int,
    correlation_id: str | None,
    payload: dict[str, Any],
) -> int:
    record = TrainerAgentViewModelRecord.objects.create(
        session_id=session_id,
        state_revision=state_revision,
        correlation_id=correlation_id or "",
        builder_version=VIEWMODEL_BUILDER_VERSION,
        schema_version=VIEWMODEL_SCHEMA_VERSION,
        payload_json=payload,
    )
    logger.info(
        "trainerlab.agent_view_model.persisted",
        session_id=session_id,
        correlation_id=correlation_id,
        agent_view_model_record_id=record.id,
        state_revision=state_revision,
    )
    return record.id


def _attach_service_call_to_agent_view_model_record(*, record_id: int, call_id: str) -> None:
    TrainerAgentViewModelRecord.objects.filter(pk=record_id).update(service_call_id=call_id)


def _normalize_runtime_request_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metrics)
    if normalized.get("service_call_id") is not None:
        normalized["service_call_id"] = str(normalized["service_call_id"])
    if normalized.get("correlation_id") is not None:
        normalized["correlation_id"] = str(normalized["correlation_id"])
    return normalized


def _emit_runtime_failure_event(
    *,
    session_id: int,
    reasons: list[dict[str, Any]],
    correlation_id: str | None,
    error: str,
    reason_code: str | None = None,
    retryable: bool | None = None,
    service_call_id: str | None = None,
) -> None:
    session = TrainerSession.objects.select_related("simulation").get(pk=session_id)
    payload = {
        "error": error,
        "reasons": reasons,
    }
    if reason_code:
        payload["reason_code"] = reason_code
    if retryable is not None:
        payload["retryable"] = retryable
    if service_call_id:
        payload["service_call_id"] = service_call_id
    emit_runtime_event(
        session=session,
        event_type=outbox_events.SIMULATION_RUNTIME_FAILED,
        payload=payload,
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.SIMULATION_RUNTIME_FAILED}:{session.id}:{timezone.now().timestamp()}"
        ),
    )


def _build_runtime_request_batch(batch: dict[str, Any]) -> dict[str, Any]:
    from .orca.services import GenerateTrainerRuntimeTurn

    aggregate = batch["aggregate"]
    session = aggregate.session
    trainer_agent_view_model = build_trainer_agent_view_model(
        aggregate,
        reasons=list(batch["reasons"]),
    )
    trainer_agent_view_model_payload = trainer_agent_view_model.model_dump(mode="json")
    request_model = GenerateTrainerRuntimeTurn(
        context={
            "simulation_id": batch["simulation_id"],
            "session_id": batch["session_id"],
        }
    ).effective_model
    budget_result = enforce_runtime_token_budget(
        service_cls=GenerateTrainerRuntimeTurn,
        session=session,
        scenario_snapshot=trainer_agent_view_model_payload["scenario_snapshot"],
        runtime_reasons=batch["reasons"],
        active_elapsed_seconds=batch["active_elapsed_seconds"],
        user_message=RUNTIME_TURN_USER_MESSAGE,
        request_model=request_model,
        max_prompt_tokens=get_runtime_max_prompt_tokens(),
        max_output_tokens=get_runtime_max_output_tokens(),
        max_reasons=get_runtime_max_batch_reasons(),
    )
    metrics = {
        **budget_result.metrics,
        "correlation_id": batch.get("correlation_id"),
        "service_call_id": None,
        "trainer_agent_view_model_record_id": None,
    }
    return {
        **batch,
        "request_model": request_model,
        "trainer_agent_view_model": trainer_agent_view_model_payload,
        "runtime_llm_context": budget_result.runtime_llm_context,
        "runtime_reasons": budget_result.runtime_reasons,
        "runtime_request_metrics": metrics,
        "budget_allowed": budget_result.allowed,
        "budget_error_code": budget_result.error_code,
        "budget_error_message": budget_result.error_message,
    }


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

        reasons, remaining = _select_runtime_batch_reasons(
            pending=pending,
            session_status=session.status,
        )

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
        debug = dict(state.get("control_plane_debug") or {})
        debug["execution_plan"] = ["core_runtime", "vitals", "recommendation", "narrative"]
        debug["current_step_index"] = 0
        debug["queued_reasons"] = remaining
        debug["currently_processing_reasons"] = reasons
        debug["last_failed_step"] = ""
        debug["last_failed_error"] = ""
        debug["status_flags"] = {
            **dict(debug.get("status_flags") or {}),
            "runtime_processing": True,
        }
        state["control_plane_debug"] = debug
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])

        aggregate = load_trainer_engine_aggregate(
            session=session,
            runtime_state_override=state,
        )
        return {
            "session_id": session.id,
            "simulation_id": session.simulation_id,
            "reasons": reasons,
            "active_elapsed_seconds": active_elapsed_seconds,
            "aggregate": aggregate,
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
        debug = dict(state.get("control_plane_debug") or {})
        debug["queued_reasons"] = state["pending_runtime_reasons"]
        debug["currently_processing_reasons"] = []
        debug["last_failed_error"] = error[:500]
        debug["status_flags"] = {
            **dict(debug.get("status_flags") or {}),
            "runtime_processing": False,
        }
        state["control_plane_debug"] = debug
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])


def enqueue_runtime_turn_service_call(batch: dict[str, Any]) -> str:
    from .orca.services import GenerateTrainerRuntimeTurn

    context = {
        "simulation_id": batch["simulation_id"],
        "session_id": batch["session_id"],
        "trainer_agent_view_model": batch["trainer_agent_view_model"],
        "runtime_reasons": batch["runtime_reasons"],
        "active_elapsed_seconds": batch["active_elapsed_seconds"],
        "runtime_llm_context": batch["runtime_llm_context"],
        "runtime_request_metrics": batch["runtime_request_metrics"],
        "model_settings": {
            "max_tokens": get_runtime_max_output_tokens(),
        },
        "correlation_id": batch.get("correlation_id"),
        "trainer_agent_view_model_record_id": batch.get("trainer_agent_view_model_record_id"),
    }
    context.pop("previous_response_id", None)
    context.pop("previous_provider_response_id", None)
    return str(
        GenerateTrainerRuntimeTurn.task.using(
            context=context,
        ).enqueue(
            user_message=RUNTIME_TURN_USER_MESSAGE,
        )
    )


def process_runtime_turn_queue(*, session_id: int) -> str | None:
    # ── Guard service entry ─────────────────────────────────────────
    # Every runtime call passes through the shared guard entrypoint.
    from apps.guards.services import guard_service_entry

    batch = _claim_runtime_turn_batch(session_id)
    if batch is None:
        return None

    guard_decision = guard_service_entry(
        batch["simulation_id"],
        active_elapsed=batch.get("active_elapsed_seconds", 0),
    )
    if not guard_decision.allowed:
        _restore_runtime_turn_batch(
            session_id=session_id,
            reasons=batch["reasons"],
            error=guard_decision.denial_message or "Guard denied",
        )
        _emit_runtime_failure_event(
            session_id=session_id,
            reasons=batch["reasons"],
            correlation_id=batch.get("correlation_id"),
            error=guard_decision.denial_message or "Guard denied",
            reason_code=guard_decision.denial_reason or "guard_denied",
            retryable=False,
        )
        return None

    try:
        request_batch = _build_runtime_request_batch(batch)
        agent_view_model_record_id = _persist_trainer_agent_view_model_record(
            session_id=session_id,
            state_revision=int(
                request_batch["trainer_agent_view_model"]["runtime_snapshot"]["state_revision"] or 0
            ),
            correlation_id=batch.get("correlation_id"),
            payload=request_batch["trainer_agent_view_model"],
        )
        request_batch["trainer_agent_view_model_record_id"] = agent_view_model_record_id
        request_batch["runtime_request_metrics"] = {
            **request_batch["runtime_request_metrics"],
            "trainer_agent_view_model_record_id": agent_view_model_record_id,
        }
        _update_runtime_request_profile(
            session_id=session_id,
            metrics=request_batch["runtime_request_metrics"],
        )
        logger.info(
            "trainerlab.runtime.request_profiled",
            **request_batch["runtime_request_metrics"],
        )
    except Exception as exc:
        logger.exception("trainerlab.runtime.request_build_failed", session_id=session_id)
        _restore_runtime_turn_batch(
            session_id=session_id,
            reasons=batch["reasons"],
            error=str(exc),
        )
        _emit_runtime_failure_event(
            session_id=session_id,
            reasons=batch["reasons"],
            correlation_id=batch.get("correlation_id"),
            error=str(exc),
            reason_code="runtime_request_build_failed",
            retryable=False,
        )
        return None

    if not request_batch["budget_allowed"]:
        error_message = request_batch["budget_error_message"] or "Runtime prompt budget exceeded"
        _restore_runtime_turn_batch(
            session_id=session_id,
            reasons=batch["reasons"],
            error=error_message,
        )
        _emit_runtime_failure_event(
            session_id=session_id,
            reasons=batch["reasons"],
            correlation_id=batch.get("correlation_id"),
            error=error_message,
            reason_code=request_batch["budget_error_code"],
            retryable=False,
        )
        return None

    try:
        call_id = enqueue_runtime_turn_service_call(request_batch)
        return call_id
    except Exception as exc:
        logger.exception("trainerlab.runtime.enqueue_failed", session_id=session_id)
        _restore_runtime_turn_batch(
            session_id=session_id,
            reasons=batch["reasons"],
            error=str(exc),
        )
        _emit_runtime_failure_event(
            session_id=session_id,
            reasons=batch["reasons"],
            correlation_id=batch.get("correlation_id"),
            error=str(exc),
            retryable=True,
        )
        raise
    finally:
        if "call_id" in locals():
            request_metrics = {
                **request_batch["runtime_request_metrics"],
                "service_call_id": call_id,
            }
            try:
                _attach_service_call_to_agent_view_model_record(
                    record_id=agent_view_model_record_id,
                    call_id=call_id,
                )
                _persist_runtime_request_metrics(call_id=call_id, metrics=request_metrics)
                _update_runtime_request_profile(session_id=session_id, metrics=request_metrics)
            except Exception:
                logger.exception(
                    "trainerlab.runtime.request_profile_persist_failed",
                    session_id=session_id,
                    service_call_id=call_id,
                )


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
        debug = dict(state.get("control_plane_debug") or {})
        debug["queued_reasons"] = pending
        debug["currently_processing_reasons"] = []
        debug["last_failed_error"] = error[:500]
        debug["status_flags"] = {
            **dict(debug.get("status_flags") or {}),
            "runtime_processing": False,
        }
        state["control_plane_debug"] = debug
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])


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


_SEVERITY_ORDER = {
    Problem.Severity.LOW: 0,
    Problem.Severity.MODERATE: 1,
    Problem.Severity.HIGH: 2,
    Problem.Severity.CRITICAL: 3,
}


def _severity_rank(value: str | None) -> int:
    return _SEVERITY_ORDER.get(value or Problem.Severity.MODERATE, 1)


def _next_worse_severity(value: str | None) -> str:
    for candidate in (
        Problem.Severity.LOW,
        Problem.Severity.MODERATE,
        Problem.Severity.HIGH,
        Problem.Severity.CRITICAL,
    ):
        if _severity_rank(candidate) > _severity_rank(value):
            return candidate
    return Problem.Severity.CRITICAL


def _next_better_severity(value: str | None) -> str:
    ordered = (
        Problem.Severity.LOW,
        Problem.Severity.MODERATE,
        Problem.Severity.HIGH,
        Problem.Severity.CRITICAL,
    )
    current_rank = _severity_rank(value)
    for candidate in reversed(ordered):
        if _severity_rank(candidate) < current_rank:
            return candidate
    return Problem.Severity.LOW


def _problem_age_seconds(problem: Problem) -> int:
    return max(0, int((timezone.now() - problem.timestamp).total_seconds()))


def _resolve_active_cause(
    *,
    session: TrainerSession,
    cause_kind: str,
    cause_id: int,
) -> Injury | Illness | None:
    if cause_kind == "injury":
        return Injury.objects.filter(
            simulation=session.simulation,
            pk=cause_id,
            is_active=True,
        ).first()
    return Illness.objects.filter(
        simulation=session.simulation,
        pk=cause_id,
        is_active=True,
    ).first()


def _existing_problem_for_observation(
    *,
    session: TrainerSession,
    cause: Injury | Illness,
    kind: str,
    parent_problem: Problem | None,
) -> Problem | None:
    filters = {
        "simulation": session.simulation,
        "is_active": True,
        "kind": kind,
        "parent_problem": parent_problem,
    }
    if isinstance(cause, Injury):
        filters["cause_injury"] = cause
    else:
        filters["cause_illness"] = cause
    return (
        Problem.objects.select_related("cause_injury", "cause_illness", "parent_problem")
        .filter(**filters)
        .order_by("-timestamp", "-id")
        .first()
    )


def _create_problem_domain_event(
    *,
    session: TrainerSession,
    cause: Injury | Illness,
    kind: str,
    title: str,
    description: str,
    march_category: str | None,
    severity: str | None,
    anatomical_location: str,
    laterality: str,
    parent_problem: Problem | None,
    supersedes: Problem | None = None,
    previous_status: str = "",
    adjudication_reason: str = "",
    adjudication_rule_id: str = "",
) -> Problem:
    definition = get_problem_definition(kind)
    return Problem.objects.create(
        simulation=session.simulation,
        source=EventSource.SYSTEM,
        supersedes=supersedes,
        cause_injury=cause if isinstance(cause, Injury) else None,
        cause_illness=cause if isinstance(cause, Illness) else None,
        parent_problem=parent_problem,
        problem_kind=(
            Problem.ProblemKind.INJURY if isinstance(cause, Injury) else Problem.ProblemKind.ILLNESS
        ),
        kind=definition.kind,
        code=definition.code,
        slug=definition.slug,
        title=title or definition.title,
        display_name=title or definition.title,
        description=description,
        march_category=march_category
        or definition.default_march_category
        or Problem.MARCHCategory.C,
        severity=severity or Problem.Severity.MODERATE,
        anatomical_location=anatomical_location,
        laterality=laterality,
        status=supersedes.status if supersedes is not None else Problem.Status.ACTIVE,
        previous_status=previous_status,
        adjudication_reason=adjudication_reason,
        adjudication_rule_id=adjudication_rule_id,
    )


def _apply_problem_observation(
    *,
    session: TrainerSession,
    observation: dict[str, Any],
    correlation_id: str | None,
) -> None:
    normalized_kind = normalize_problem_kind(observation.get("problem_kind"))
    definition = get_problem_definition(normalized_kind)
    parent_problem = (
        Problem.objects.filter(
            simulation=session.simulation,
            pk=observation.get("parent_problem_id"),
            is_active=True,
        ).first()
        if observation.get("parent_problem_id")
        else None
    )

    if observation.get("observation") == "new_problem":
        cause = _resolve_active_cause(
            session=session,
            cause_kind=str(observation.get("cause_kind")),
            cause_id=int(observation.get("cause_id")),
        )
        if cause is None:
            return
        existing = _existing_problem_for_observation(
            session=session,
            cause=cause,
            kind=definition.kind,
            parent_problem=parent_problem,
        )
        if existing is not None:
            observation = {
                **observation,
                "target_problem_id": existing.id,
                "observation": "worsening",
            }
        else:
            created = _create_problem_domain_event(
                session=session,
                cause=cause,
                kind=definition.kind,
                title=str(observation.get("title") or definition.title),
                description=str(observation.get("description") or ""),
                march_category=observation.get("march_category"),
                severity=observation.get("severity"),
                anatomical_location=str(
                    observation.get("anatomical_location")
                    or getattr(cause, "anatomical_location", "")
                    or ""
                ),
                laterality=str(
                    observation.get("laterality") or getattr(cause, "laterality", "") or ""
                ),
                parent_problem=parent_problem,
                adjudication_reason="runtime_observation",
                adjudication_rule_id="runtime.observation.new_problem",
            )
            emit_domain_runtime_event(
                session=session,
                event_type=outbox_events.PATIENT_PROBLEM_CREATED,
                obj=created,
                extra={"action": "created"},
                correlation_id=correlation_id,
                idempotency_key=f"{outbox_events.PATIENT_PROBLEM_CREATED}:runtime:{created.id}",
            )
            return

    target_problem = (
        Problem.objects.select_related("cause_injury", "cause_illness", "parent_problem")
        .filter(
            simulation=session.simulation,
            pk=observation.get("target_problem_id"),
            is_active=True,
        )
        .first()
    )
    if target_problem is None:
        return

    next_severity = observation.get("severity") or target_problem.severity
    if observation.get("observation") == "worsening" and not observation.get("severity"):
        next_severity = _next_worse_severity(target_problem.severity)
    elif observation.get("observation") == "improving" and not observation.get("severity"):
        next_severity = _next_better_severity(target_problem.severity)

    next_description = str(observation.get("description") or target_problem.description)
    next_location = str(
        observation.get("anatomical_location") or target_problem.anatomical_location
    )
    next_laterality = str(observation.get("laterality") or target_problem.laterality)
    next_title = str(observation.get("title") or target_problem.title)
    next_march = observation.get("march_category") or target_problem.march_category

    if (
        next_severity == target_problem.severity
        and next_description == target_problem.description
        and next_location == target_problem.anatomical_location
        and next_laterality == target_problem.laterality
        and next_title == target_problem.title
        and next_march == target_problem.march_category
    ):
        return

    _deactivate_event(target_problem)
    updated = _create_problem_domain_event(
        session=session,
        cause=target_problem.cause,
        kind=target_problem.kind,
        title=next_title,
        description=next_description,
        march_category=next_march,
        severity=next_severity,
        anatomical_location=next_location,
        laterality=next_laterality,
        parent_problem=target_problem.parent_problem,
        supersedes=target_problem,
        previous_status=target_problem.status,
        adjudication_reason="runtime_observation",
        adjudication_rule_id=f"runtime.observation.{observation.get('observation', 'stable')}",
    )
    emit_domain_runtime_event(
        session=session,
        event_type=outbox_events.PATIENT_PROBLEM_UPDATED,
        obj=updated,
        extra={"action": "updated"},
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.PATIENT_PROBLEM_UPDATED}:runtime:{updated.id}",
    )


def _ensure_secondary_problem(
    *,
    session: TrainerSession,
    parent_problem: Problem,
    kind: str,
    severity: str,
    description: str,
    rule_id: str,
    correlation_id: str | None,
) -> None:
    existing = _existing_problem_for_observation(
        session=session,
        cause=parent_problem.cause,
        kind=kind,
        parent_problem=parent_problem,
    )
    if existing is not None:
        if _severity_rank(existing.severity) >= _severity_rank(severity):
            return
        _deactivate_event(existing)
        updated = _create_problem_domain_event(
            session=session,
            cause=parent_problem.cause,
            kind=kind,
            title=get_problem_definition(kind).title,
            description=description,
            march_category=get_problem_definition(kind).default_march_category,
            severity=severity,
            anatomical_location=parent_problem.anatomical_location,
            laterality=parent_problem.laterality,
            parent_problem=parent_problem,
            supersedes=existing,
            previous_status=existing.status,
            adjudication_reason="deterministic_progression",
            adjudication_rule_id=rule_id,
        )
        emit_domain_runtime_event(
            session=session,
            event_type=outbox_events.PATIENT_PROBLEM_UPDATED,
            obj=updated,
            extra={"action": "updated"},
            correlation_id=correlation_id,
            idempotency_key=f"{outbox_events.PATIENT_PROBLEM_UPDATED}:{rule_id}:{updated.id}",
        )
        return

    created = _create_problem_domain_event(
        session=session,
        cause=parent_problem.cause,
        kind=kind,
        title=get_problem_definition(kind).title,
        description=description,
        march_category=get_problem_definition(kind).default_march_category,
        severity=severity,
        anatomical_location=parent_problem.anatomical_location,
        laterality=parent_problem.laterality,
        parent_problem=parent_problem,
        adjudication_reason="deterministic_progression",
        adjudication_rule_id=rule_id,
    )
    emit_domain_runtime_event(
        session=session,
        event_type=outbox_events.PATIENT_PROBLEM_CREATED,
        obj=created,
        extra={"action": "created"},
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.PATIENT_PROBLEM_CREATED}:{rule_id}:{created.id}",
    )


def _apply_progression_catalogs(
    *,
    session: TrainerSession,
    correlation_id: str | None,
) -> None:
    problems = list(
        Problem.objects.select_related("cause_injury", "cause_illness", "parent_problem")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    for problem in problems:
        if not problem.is_active:
            continue
        age_seconds = _problem_age_seconds(problem)
        if problem.kind == "hemorrhage" and problem.status == Problem.Status.ACTIVE:
            if (
                _severity_rank(problem.severity) >= _severity_rank(Problem.Severity.HIGH)
                and age_seconds >= 90
            ):
                _ensure_secondary_problem(
                    session=session,
                    parent_problem=problem,
                    kind="hypoperfusion_shock",
                    severity=Problem.Severity.HIGH,
                    description="Progressive shock from untreated hemorrhage.",
                    rule_id="progression.hemorrhage_to_shock",
                    correlation_id=correlation_id,
                )
        elif problem.kind == "open_chest_wound" and problem.status in {
            Problem.Status.ACTIVE,
            Problem.Status.TREATED,
        }:
            if age_seconds >= 60:
                _ensure_secondary_problem(
                    session=session,
                    parent_problem=problem,
                    kind="respiratory_distress",
                    severity=Problem.Severity.HIGH,
                    description="Respiratory distress from ongoing chest injury.",
                    rule_id="progression.open_chest_wound_to_respiratory_distress",
                    correlation_id=correlation_id,
                )
        elif problem.kind == "respiratory_distress" and problem.status == Problem.Status.ACTIVE:
            if age_seconds >= 120:
                _ensure_secondary_problem(
                    session=session,
                    parent_problem=problem,
                    kind="tension_pneumothorax",
                    severity=Problem.Severity.CRITICAL,
                    description="Worsening respiratory distress progressing to tension physiology.",
                    rule_id="progression.respiratory_distress_to_tension_pneumothorax",
                    correlation_id=correlation_id,
                )
        elif problem.kind == "airway_obstruction" and problem.status == Problem.Status.ACTIVE:
            if age_seconds >= 45:
                _ensure_secondary_problem(
                    session=session,
                    parent_problem=problem,
                    kind="hypoxia",
                    severity=Problem.Severity.HIGH,
                    description="Hypoxia from persistent airway obstruction.",
                    rule_id="progression.airway_obstruction_to_hypoxia",
                    correlation_id=correlation_id,
                )
        elif (
            problem.kind == "infectious_process"
            and problem.status == Problem.Status.ACTIVE
            and age_seconds >= 300
            and _severity_rank(problem.severity) < _severity_rank(Problem.Severity.HIGH)
        ):
            _deactivate_event(problem)
            updated = _create_problem_domain_event(
                session=session,
                cause=problem.cause,
                kind=problem.kind,
                title=problem.title,
                description=problem.description or "Untreated infectious process is worsening.",
                march_category=problem.march_category,
                severity=Problem.Severity.HIGH,
                anatomical_location=problem.anatomical_location,
                laterality=problem.laterality,
                parent_problem=problem.parent_problem,
                supersedes=problem,
                previous_status=problem.status,
                adjudication_reason="deterministic_progression",
                adjudication_rule_id="progression.infectious_process_worsening",
            )
            emit_domain_runtime_event(
                session=session,
                event_type=outbox_events.PATIENT_PROBLEM_UPDATED,
                obj=updated,
                extra={"action": "updated"},
                correlation_id=correlation_id,
                idempotency_key=f"{outbox_events.PATIENT_PROBLEM_UPDATED}:progression:{updated.id}",
            )


def _apply_finding_update(
    *,
    session: TrainerSession,
    change: dict[str, Any],
    correlation_id: str | None,
) -> None:
    target_finding = (
        AssessmentFinding.objects.select_related("target_problem")
        .filter(
            simulation=session.simulation,
            pk=change.get("target_finding_id"),
            is_active=True,
        )
        .first()
        if change.get("target_finding_id")
        else None
    )
    if change.get("action") == "remove":
        deactivate_domain_object(
            session=session,
            obj=target_finding,
            correlation_id=correlation_id,
            action="removed",
        )
        return

    definition = get_finding_definition(change.get("finding_kind"))
    target_problem = (
        Problem.objects.filter(
            simulation=session.simulation,
            pk=change.get("target_problem_id"),
            is_active=True,
        ).first()
        if change.get("target_problem_id")
        else getattr(target_finding, "target_problem", None)
    )
    if target_finding is not None:
        _deactivate_event(target_finding)

    finding = AssessmentFinding.objects.create(
        simulation=session.simulation,
        source=EventSource.SYSTEM,
        supersedes=target_finding,
        target_problem=target_problem,
        kind=definition.kind,
        code=definition.code,
        slug=definition.slug,
        title=str(change.get("title") or definition.title),
        display_name=str(change.get("title") or definition.title),
        description=str(change.get("description") or getattr(target_finding, "description", "")),
        status=str(
            change.get("status")
            or getattr(target_finding, "status", AssessmentFinding.Status.PRESENT)
        ),
        severity=str(
            change.get("severity")
            or getattr(target_finding, "severity", AssessmentFinding.Severity.MODERATE)
        ),
        anatomical_location=str(
            change.get("anatomical_location") or getattr(target_finding, "anatomical_location", "")
        ),
        laterality=str(change.get("laterality") or getattr(target_finding, "laterality", "")),
        metadata_json=dict(change.get("metadata") or getattr(target_finding, "metadata_json", {})),
    )
    emit_domain_runtime_event(
        session=session,
        event_type=(
            outbox_events.PATIENT_ASSESSMENT_FINDING_UPDATED
            if target_finding is not None
            else outbox_events.PATIENT_ASSESSMENT_FINDING_CREATED
        ),
        obj=finding,
        correlation_id=correlation_id,
        idempotency_key=f"patient.assessmentfinding:{finding.id}",
    )


def _contraindicated_interventions(session: TrainerSession) -> set[str]:
    values: set[str] = set()
    for model in (AssessmentFinding, DiagnosticResult):
        for obj in model.objects.filter(simulation=session.simulation, is_active=True):
            for item in obj.metadata_json.get("contraindicated_interventions", []):
                values.add(str(item))
    return values


def _resource_constraints(session: TrainerSession) -> tuple[set[str], set[str]]:
    unavailable: set[str] = set()
    limited: set[str] = set()
    for resource in ResourceState.objects.filter(simulation=session.simulation, is_active=True):
        code = resource.code or resource.kind
        if (
            resource.status in {ResourceState.Status.UNAVAILABLE, ResourceState.Status.DEPLETED}
            or resource.quantity_available <= 0
        ):
            unavailable.add(code)
        elif resource.status == ResourceState.Status.LIMITED or resource.quantity_available <= 1:
            limited.add(code)
    return unavailable, limited


def _recommendation_key(payload: dict[str, Any]) -> tuple[int, str, str]:
    return (
        int(payload["target_problem_id"]),
        str(payload["kind"]),
        str(payload.get("site_code") or ""),
    )


def _record_recommendation_evaluation(
    *,
    session: TrainerSession,
    problem: Problem,
    suggestion: dict[str, Any],
    normalization,
    recommendation: RecommendedIntervention | None,
    correlation_id: str | None,
) -> None:
    evaluation = RecommendationEvaluation.objects.create(
        simulation=session.simulation,
        source=EventSource.SYSTEM,
        recommendation=recommendation,
        target_problem=problem,
        target_injury=problem.cause if isinstance(problem.cause, Injury) else None,
        target_illness=problem.cause if isinstance(problem.cause, Illness) else None,
        raw_kind=str(suggestion.get("intervention_kind") or ""),
        raw_title=str(suggestion.get("title") or ""),
        raw_site=str(suggestion.get("site") or ""),
        normalized_kind=normalization.kind,
        normalized_code=normalization.code,
        title=normalization.title or str(suggestion.get("title") or ""),
        recommendation_source=normalization.recommendation_source,
        validation_status=normalization.validation_status,
        rationale=normalization.rationale or str(suggestion.get("rationale") or ""),
        priority=normalization.priority,
        warnings_json=list(normalization.warnings),
        contraindications_json=list(normalization.contraindications),
        rejection_reason=str(normalization.metadata.get("rejection_reason", "")),
        metadata_json=dict(normalization.metadata or {}),
    )
    emit_domain_runtime_event(
        session=session,
        event_type=outbox_events.PATIENT_RECOMMENDATION_EVALUATION_CREATED,
        obj=evaluation,
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.PATIENT_RECOMMENDATION_EVALUATION_CREATED}:{evaluation.id}"
        ),
    )


def recompute_active_recommendations(
    *,
    session: TrainerSession,
    ai_suggestions: list[dict[str, Any]] | None = None,
    correlation_id: str | None = None,
) -> None:
    problems = list(
        Problem.objects.select_related("cause_injury", "cause_illness")
        .filter(simulation=session.simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    current = {
        _recommendation_key(serialize_recommendation_summary(item)): item
        for item in RecommendedIntervention.objects.select_related(
            "target_problem", "target_injury", "target_illness"
        ).filter(simulation=session.simulation, is_active=True)
    }
    unavailable_interventions, limited_interventions = _resource_constraints(session)
    contraindicated_interventions = _contraindicated_interventions(session)

    desired: dict[tuple[int, str, str], dict[str, Any]] = {}
    for suggestion in ai_suggestions or []:
        problem = next(
            (item for item in problems if item.id == suggestion.get("target_problem_id")), None
        )
        if problem is None:
            continue
        normalization = validate_and_normalize_recommendation(
            problem=problem,
            raw_kind=str(suggestion.get("intervention_kind") or ""),
            raw_title=str(suggestion.get("title") or ""),
            raw_site=str(suggestion.get("site") or ""),
            rationale=str(suggestion.get("rationale") or ""),
            priority=suggestion.get("priority"),
            warnings=list(suggestion.get("warnings") or []),
            contraindications=list(suggestion.get("contraindications") or []),
            metadata=dict(suggestion.get("metadata") or {}),
            contraindicated_interventions=contraindicated_interventions,
            unavailable_interventions=unavailable_interventions,
            limited_interventions=limited_interventions,
            source_override=RecommendedIntervention.RecommendationSource.AI,
        )
        if normalization.accepted:
            desired[(problem.id, normalization.kind, normalization.site_code)] = {
                "problem": problem,
                "source": normalization.recommendation_source,
                "validation_status": normalization.validation_status,
                "kind": normalization.kind,
                "code": normalization.code,
                "slug": normalization.slug,
                "title": normalization.title,
                "display_name": normalization.display_name,
                "site_code": normalization.site_code,
                "site_label": normalization.site_label,
                "rationale": normalization.rationale,
                "priority": normalization.priority,
                "warnings": normalization.warnings,
                "contraindications": normalization.contraindications,
                "metadata": normalization.metadata,
            }
        _record_recommendation_evaluation(
            session=session,
            problem=problem,
            suggestion=suggestion,
            normalization=normalization,
            recommendation=None,
            correlation_id=correlation_id,
        )

    for problem in problems:
        for seed in generate_rule_based_recommendations(problem):
            normalization = validate_and_normalize_recommendation(
                problem=problem,
                raw_kind=seed.intervention_kind,
                raw_title=seed.title,
                raw_site=seed.raw_site,
                rationale=seed.rationale,
                priority=seed.priority,
                warnings=seed.warnings,
                contraindications=seed.contraindications,
                metadata=seed.metadata,
                contraindicated_interventions=contraindicated_interventions,
                unavailable_interventions=unavailable_interventions,
                limited_interventions=limited_interventions,
                source_override=RecommendedIntervention.RecommendationSource.RULES,
            )
            key = (problem.id, normalization.kind, normalization.site_code)
            recommendation_obj = None
            if normalization.accepted:
                existing = desired.get(key)
                if existing:
                    existing["source"] = RecommendedIntervention.RecommendationSource.MERGED
                    existing["validation_status"] = (
                        RecommendedIntervention.ValidationStatus.NORMALIZED
                        if normalization.validation_status
                        != RecommendedIntervention.ValidationStatus.ACCEPTED
                        or existing["validation_status"]
                        != RecommendedIntervention.ValidationStatus.ACCEPTED
                        else RecommendedIntervention.ValidationStatus.ACCEPTED
                    )
                    existing["warnings"] = list(
                        {*(existing["warnings"] or []), *(normalization.warnings or [])}
                    )
                    if existing["priority"] is None or (
                        normalization.priority is not None
                        and normalization.priority < existing["priority"]
                    ):
                        existing["priority"] = normalization.priority
                else:
                    desired[key] = {
                        "problem": problem,
                        "source": normalization.recommendation_source,
                        "validation_status": normalization.validation_status,
                        "kind": normalization.kind,
                        "code": normalization.code,
                        "slug": normalization.slug,
                        "title": normalization.title,
                        "display_name": normalization.display_name,
                        "site_code": normalization.site_code,
                        "site_label": normalization.site_label,
                        "rationale": normalization.rationale,
                        "priority": normalization.priority,
                        "warnings": normalization.warnings,
                        "contraindications": normalization.contraindications,
                        "metadata": normalization.metadata,
                    }
            _record_recommendation_evaluation(
                session=session,
                problem=problem,
                suggestion={
                    "intervention_kind": seed.intervention_kind,
                    "title": seed.title,
                    "site": seed.raw_site,
                    "rationale": seed.rationale,
                    "priority": seed.priority,
                    "metadata": seed.metadata,
                },
                normalization=normalization,
                recommendation=recommendation_obj,
                correlation_id=correlation_id,
            )

    for key, existing in current.items():
        if key not in desired:
            deactivate_domain_object(
                session=session,
                obj=existing,
                correlation_id=correlation_id,
                action="removed",
            )

    for key, payload in desired.items():
        existing = current.get(key)
        needs_update = existing is None or any(
            [
                existing.recommendation_source != payload["source"],
                existing.validation_status != payload["validation_status"],
                existing.display_name != payload["display_name"],
                existing.rationale != payload["rationale"],
                existing.priority != payload["priority"],
                list(existing.warnings_json or []) != list(payload["warnings"] or []),
                list(existing.contraindications_json or [])
                != list(payload["contraindications"] or []),
            ]
        )
        if not needs_update:
            continue
        if existing is not None:
            _deactivate_event(existing)
        recommendation = RecommendedIntervention.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            supersedes=existing,
            kind=payload["kind"],
            code=payload["code"],
            slug=payload["slug"],
            title=payload["title"],
            display_name=payload["display_name"],
            description="",
            target_problem=payload["problem"],
            target_injury=payload["problem"].cause
            if isinstance(payload["problem"].cause, Injury)
            else None,
            target_illness=payload["problem"].cause
            if isinstance(payload["problem"].cause, Illness)
            else None,
            recommendation_source=payload["source"],
            validation_status=payload["validation_status"],
            normalized_kind=payload["kind"],
            normalized_code=payload["code"],
            rationale=payload["rationale"],
            priority=payload["priority"],
            site_code=payload["site_code"],
            site_label=payload["site_label"],
            contraindications_json=payload["contraindications"],
            warnings_json=payload["warnings"],
            metadata_json=payload["metadata"],
        )
        emit_domain_runtime_event(
            session=session,
            event_type=(
                outbox_events.PATIENT_RECOMMENDED_INTERVENTION_UPDATED
                if existing is not None
                else outbox_events.PATIENT_RECOMMENDED_INTERVENTION_CREATED
            ),
            obj=recommendation,
            correlation_id=correlation_id,
            idempotency_key=f"patient.recommendedintervention:{recommendation.id}",
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
        "source": EventSource.SYSTEM,
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
        event_type=outbox_events.PATIENT_VITAL_UPDATED,
        payload=payload,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.PATIENT_VITAL_UPDATED}:{created.id}",
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
        source=EventSource.SYSTEM,
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
        event_type=outbox_events.PATIENT_PULSE_UPDATED,
        payload=payload,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.PATIENT_PULSE_UPDATED}:{created.id}",
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

    intervention.effectiveness = change.get("effectiveness", intervention.effectiveness)
    if change.get("notes"):
        intervention.notes = str(change.get("notes"))
    intervention.save(update_fields=["effectiveness", "notes"])

    effects = dict(state.get("intervention_effects") or {})
    effects[str(intervention.id)] = {
        "status": change.get("status", "active"),
        "clinical_effect": change.get("clinical_effect", ""),
        "notes": intervention.notes,
    }
    state["intervention_effects"] = effects

    emit_runtime_event(
        session=session,
        event_type=outbox_events.PATIENT_INTERVENTION_UPDATED,
        payload=serialize_domain_event(
            intervention,
            extra={
                "assessment_status": effects[str(intervention.id)]["status"],
                "effect": effects[str(intervention.id)],
            },
        ),
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.PATIENT_INTERVENTION_UPDATED}:{intervention.id}:"
            f"{effects[str(intervention.id)]['status']}"
        ),
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


def _driver_intervention_ids(reasons: list[dict[str, Any]]) -> list[int]:
    driver_ids: list[int] = []
    for reason in reasons:
        payload = dict(reason.get("payload") or {})
        intervention_id = payload.get("intervention_event_id")
        if intervention_id is None and payload.get("event_kind") == "intervention":
            intervention_id = payload.get("domain_event_id")
        if isinstance(intervention_id, int) and intervention_id not in driver_ids:
            driver_ids.append(intervention_id)
    return driver_ids


def _driver_reason_kinds(reasons: list[dict[str, Any]]) -> list[str]:
    kinds: list[str] = []
    for reason in reasons:
        reason_kind = str(reason.get("reason_kind") or "")
        if reason_kind and reason_kind not in kinds:
            kinds.append(reason_kind)
    return kinds


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
        touched_domains: list[str] = []

        state_changes = dict(output_payload.get("state_changes") or {})

        evaluation_summary = {
            "worker_kind": "core_runtime",
            "domains": touched_domains,
            "driver_reason_kinds": _driver_reason_kinds(processed_reasons),
            "driver_intervention_ids": _driver_intervention_ids(processed_reasons),
            "accepted": [],
            "normalized": [],
            "rejected": [],
            "source_call_id": str(service_context.get("call_id") or ""),
            "correlation_id": correlation_id,
        }
        for observation in state_changes.get("problem_observations", []):
            _apply_problem_observation(
                session=session,
                observation=observation,
                correlation_id=correlation_id,
            )
            if "problem" not in touched_domains:
                touched_domains.append("problem")
            evaluation_summary["accepted"].append(
                {"domain": "problem", "kind": "problem_observation"}
            )

        # Deterministic step 2: vitals worker owns physiology.
        for change in state_changes.get("vital_updates", []):
            _apply_vital_change(
                session=session,
                change=change,
                correlation_id=correlation_id,
            )
            if "physiology" not in touched_domains:
                touched_domains.append("physiology")
            evaluation_summary["normalized"].append(
                {
                    "domain": "physiology",
                    "kind": "vital_update",
                    "reason": "routed_to_vitals_step",
                }
            )

        for change in state_changes.get("pulse_updates", []):
            _apply_pulse_change(
                session=session,
                change=change,
                correlation_id=correlation_id,
            )
            if "physiology" not in touched_domains:
                touched_domains.append("physiology")
            evaluation_summary["normalized"].append(
                {
                    "domain": "physiology",
                    "kind": "pulse_update",
                    "reason": "routed_to_vitals_step",
                }
            )

        for change in state_changes.get("finding_updates", []):
            _apply_finding_update(
                session=session,
                change=change,
                correlation_id=correlation_id,
            )
            if "finding" not in touched_domains:
                touched_domains.append("finding")
            evaluation_summary["accepted"].append({"domain": "finding", "kind": "finding_update"})

        for change in state_changes.get("intervention_assessments", []):
            _apply_intervention_effect(
                session=session,
                change=change,
                state=state,
                correlation_id=correlation_id,
            )
            if "intervention" not in touched_domains:
                touched_domains.append("intervention")
            evaluation_summary["accepted"].append(
                {"domain": "intervention", "kind": "intervention_assessment"}
            )

        _apply_progression_catalogs(
            session=session,
            correlation_id=correlation_id,
        )
        # Deterministic step 3: recommendation worker owns recommendation output.
        recompute_active_recommendations(
            session=session,
            ai_suggestions=list(state_changes.get("recommendation_suggestions") or []),
            correlation_id=correlation_id,
        )
        if state_changes.get("recommendation_suggestions"):
            if "recommendation" not in touched_domains:
                touched_domains.append("recommendation")
            evaluation_summary["normalized"].append(
                {
                    "domain": "recommendation",
                    "kind": "recommendation_suggestion",
                    "reason": "routed_to_recommendation_step",
                }
            )
        # Deterministic step 4: narrative worker runs last and consumes canonical state.
        patient_status = _derive_patient_status_truth(
            session=session,
            base_status=dict(
                output_payload.get("patient_status") or _current_patient_status_payload(session)
            ),
        )
        if output_payload.get("patient_status") or output_payload.get("instructor_intent"):
            if "narrative" not in touched_domains:
                touched_domains.append("narrative")
            evaluation_summary["normalized"].append(
                {
                    "domain": "narrative",
                    "kind": "patient_status_or_intent",
                    "reason": "routed_to_narrative_step",
                }
            )
        state["runtime_processing"] = False
        state["currently_processing_reasons"] = []
        state["last_runtime_error"] = ""
        state["llm_conditions_check"] = list(output_payload.get("llm_conditions_check") or [])
        session.runtime_state_json = state
        session.save(update_fields=["runtime_state_json", "modified_at"])
        _persist_patient_status_state(
            session=session,
            base_status=patient_status,
            source=EventSource.AI,
        )

        refreshed = refresh_runtime_projection(
            session=session,
            correlation_id=correlation_id,
            ai_plan=dict(output_payload.get("instructor_intent") or {}),
            rationale_notes=list(output_payload.get("rationale_notes") or []),
            processed_reasons=processed_reasons,
            update_tick_timestamp=True,
        )
        debug = dict(refreshed.get("control_plane_debug") or {})
        debug["current_step_index"] = 3
        debug["currently_processing_reasons"] = []
        debug["last_processed_reasons"] = processed_reasons
        debug["status_flags"] = {
            **dict(debug.get("status_flags") or {}),
            "runtime_processing": False,
        }
        refreshed["control_plane_debug"] = debug
        session.runtime_state_json = refreshed
        session.save(update_fields=["runtime_state_json", "modified_at"])
        record_patch_evaluation_summary(
            session=session,
            correlation_id=correlation_id,
            summary=evaluation_summary,
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
            event_type=outbox_events.SIMULATION_SUMMARY_UPDATED,
            payload={
                "summary_id": summary.id,
                "status": "updated",
                "ai_debrief": output_payload,
                "ai_debrief_revision": next_revision,
            },
            correlation_id=correlation_id,
            idempotency_key=(
                f"{outbox_events.SIMULATION_SUMMARY_UPDATED}:{session.id}:{next_revision}"
            ),
        )
        return summary


def start_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.SEEDED:
        raise ValidationError("Session can only be started from seeded state")

    # ── Guard: pre-session token budget admission check ─────────────
    from apps.guards.enums import LabType
    from apps.guards.services import check_pre_session_budget, ensure_session_presence

    sim = session.simulation
    if sim.user and sim.account:
        from apps.guards.policy import _resolve_product_code

        product_code = _resolve_product_code(sim, LabType.TRAINERLAB)
        budget_decision = check_pre_session_budget(
            sim.user,
            sim.account,
            LabType.TRAINERLAB,
            product_code,
        )
        if not budget_decision.allowed:
            raise ValidationError(budget_decision.denial_message)

    ensure_session_presence(session.simulation_id, LabType.TRAINERLAB)

    previous_status = session.status
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

    emit_simulation_status_event(
        session=session,
        previous_status=previous_status,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:running",
        extra={
            "status": session.status,
            "from": previous_status,
            "to": session.status,
        },
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

    previous_status = session.status
    now = timezone.now()
    state = _freeze_active_elapsed(session, state=get_runtime_state(session), now=now)

    session.status = SessionStatus.PAUSED
    session.run_paused_at = now
    session.runtime_state_json = state
    session.save(update_fields=["status", "run_paused_at", "runtime_state_json", "modified_at"])

    emit_simulation_status_event(
        session=session,
        previous_status=previous_status,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:paused",
        extra={
            "status": session.status,
            "from": previous_status,
            "to": session.status,
        },
    )

    # Sync guard state for manual pause.
    _sync_guard_pause(session.simulation_id, pause_reason="manual")

    return session


def resume_session(
    *, session: TrainerSession, user, correlation_id: str | None = None
) -> TrainerSession:
    if session.status != SessionStatus.PAUSED:
        raise ValidationError("Session can only be resumed from paused state")

    # ── Guard: check if resume is allowed (runtime-cap pause is terminal) ──
    from apps.guards.services import resume_guard_state

    guard_decision = resume_guard_state(session.simulation_id)
    if not guard_decision.allowed:
        raise ValidationError(guard_decision.denial_message)

    previous_status = session.status
    now = timezone.now()
    state = _set_active_elapsed_anchor(session, state=get_runtime_state(session), now=now)

    session.status = SessionStatus.RUNNING
    session.run_paused_at = None
    session.tick_nonce += 1
    session.runtime_state_json = state
    session.save(
        update_fields=["status", "run_paused_at", "tick_nonce", "runtime_state_json", "modified_at"]
    )

    emit_simulation_status_event(
        session=session,
        previous_status=previous_status,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:resumed",
        extra={
            "status": session.status,
            "from": previous_status,
            "to": session.status,
        },
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

    previous_status = session.status
    terminal_at = timezone.now()
    state = _freeze_active_elapsed(session, state=get_runtime_state(session), now=terminal_at)
    state, discarded_reasons = discard_runtime_work(state, discarded_at=terminal_at)

    session.status = SessionStatus.COMPLETED
    session.run_completed_at = terminal_at
    session.runtime_state_json = state
    session.save(update_fields=["status", "run_completed_at", "runtime_state_json", "modified_at"])

    if not session.simulation.is_complete:
        session.simulation.mark_completed()

    emit_simulation_status_event(
        session=session,
        previous_status=previous_status,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:completed",
        extra={
            "status": session.status,
            "from": previous_status,
            "to": session.status,
            "discarded_runtime_reason_count": len(discarded_reasons),
        },
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
        event_type=outbox_events.SIMULATION_SUMMARY_UPDATED,
        payload={"summary_id": summary.id, "status": "ready"},
        created_by=generated_by,
        idempotency_key=f"{outbox_events.SIMULATION_SUMMARY_UPDATED}:{summary.id}:ready",
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

        _persist_patient_status_state(
            session=session,
            base_status=_current_patient_status_payload(session),
            source=EventSource.SYSTEM,
        )
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
    scenario_snapshot = _build_scenario_snapshot_for_session(
        session,
        runtime_state_override=state,
    )

    try:
        return GenerateVitalsProgression.task.using(
            context={
                "simulation_id": session.simulation_id,
                "session_id": session.id,
                "active_elapsed_seconds": get_active_elapsed_seconds(session, state=state),
                "scenario_snapshot": scenario_snapshot,
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


def update_problem_status(
    *,
    session: TrainerSession,
    problem_id: int,
    is_treated: bool | None = None,
    is_resolved: bool | None = None,
    correlation_id: str | None = None,
) -> Problem:
    """
    Update the instructor-controlled treatment/resolution state of a Problem.

    Creates a superseding event record (immutable event log) and deactivates the old one
    so the full problem history is preserved.
    """
    original: Problem | None = (
        Problem.objects.select_related("cause_injury", "cause_illness")
        .filter(
            pk=problem_id,
            simulation=session.simulation,
            is_active=True,
        )
        .first()
    )
    if original is None:
        raise ValidationError(f"Active problem {problem_id} not found for this simulation.")

    deactivate_domain_object(
        session=session,
        obj=original,
        correlation_id=correlation_id,
    )

    next_status = original.status
    if is_resolved is True:
        next_status = Problem.Status.RESOLVED
    elif is_treated is True and original.status == Problem.Status.ACTIVE:
        next_status = Problem.Status.TREATED
    elif is_treated is False and original.status == Problem.Status.TREATED:
        next_status = Problem.Status.ACTIVE

    created = Problem.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=original,
        cause_injury=original.cause_injury,
        cause_illness=original.cause_illness,
        problem_kind=original.problem_kind,
        kind=original.kind,
        code=original.code,
        slug=original.slug,
        title=original.title,
        display_name=original.display_name,
        description=original.description,
        march_category=original.march_category,
        severity=original.severity,
        anatomical_location=original.anatomical_location,
        laterality=original.laterality,
        status=next_status,
        metadata_json=original.metadata_json,
    )

    emit_domain_runtime_event(
        session=session,
        event_type=outbox_events.PATIENT_PROBLEM_UPDATED,
        obj=created,
        extra={"action": "status_updated"},
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.PATIENT_PROBLEM_UPDATED}:manual-status:{created.id}",
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
        event_type=outbox_events.SIMULATION_TICK_TRIGGERED,
        payload={
            "trigger": "manual",
            "correlation_id": correlation_id,
        },
        correlation_id=correlation_id,
        idempotency_key=(
            f"{outbox_events.SIMULATION_TICK_TRIGGERED}:{session.id}:{reason['created_at']}"
        ),
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
        event_type=outbox_events.SIMULATION_ANNOTATION_CREATED,
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
        idempotency_key=f"{outbox_events.SIMULATION_ANNOTATION_CREATED}:{annotation.id}",
    )
    return annotation


def get_session_annotations(*, session: TrainerSession) -> list[DebriefAnnotation]:
    return list(session.debrief_annotations.select_related("created_by").order_by("created_at"))


# ---------------------------------------------------------------------------
# #5 — Preset application diff
# ---------------------------------------------------------------------------


def snapshot_before_preset(session: TrainerSession) -> dict[str, Any]:
    """Capture a lightweight snapshot of active causes and vitals before preset application."""
    state = get_runtime_state(session)
    causes = []
    for model in (Injury, Illness):
        for obj in model.objects.filter(simulation=session.simulation, is_active=True):
            causes.append(
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
        "causes": causes,
        "vitals": vitals,
        "state_revision": int(state.get("state_revision", 0)),
    }


def compute_preset_diff(
    *,
    before: dict[str, Any],
    session: TrainerSession,
) -> dict[str, Any]:
    """Compare before/after snapshots and build a human-readable diff."""
    after_causes = []
    for model in (Injury, Illness):
        for obj in model.objects.filter(simulation=session.simulation, is_active=True):
            after_causes.append(
                {
                    "id": obj.id,
                    "kind": "illness" if isinstance(obj, Illness) else "injury",
                    "label": getattr(obj, "name", None) or getattr(obj, "injury_description", ""),
                }
            )
    before_ids = {cause["id"] for cause in before.get("causes", [])}
    added_causes = [cause for cause in after_causes if cause["id"] not in before_ids]

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
        "causes_added": added_causes,
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
    """Emit patient.intervention.updated when the AI evaluates an intervention."""
    intervention = Intervention.objects.filter(
        pk=intervention_id,
        simulation=session.simulation,
    ).first()
    if intervention is None:
        return

    target_problem_id: int | None = None
    target_problem_title: str | None = None
    target_problem_status: str | None = None
    if intervention.target_problem_id:
        problem = Problem.objects.filter(pk=intervention.target_problem_id).first()
        if problem:
            target_problem_id = problem.pk
            target_problem_title = problem.display_name or problem.title
            if problem.is_resolved:
                target_problem_status = "resolved"
            elif problem.is_controlled:
                target_problem_status = "controlled"
            elif problem.is_treated:
                target_problem_status = "treated"
            else:
                target_problem_status = "active"

    emit_runtime_event(
        session=session,
        event_type=outbox_events.PATIENT_INTERVENTION_UPDATED,
        payload={
            "intervention_id": intervention_id,
            "intervention_type": intervention.intervention_type or None,
            "site_code": intervention.site_code or None,
            "effectiveness": effectiveness,
            "clinical_effect": clinical_effect,
            "status": status,
            "assessment_status": status,
            "target_problem_id": target_problem_id,
            "target_problem_title": target_problem_title,
            "target_problem_status": target_problem_status,
        },
        correlation_id=correlation_id,
        idempotency_key=f"{outbox_events.PATIENT_INTERVENTION_UPDATED}:{intervention_id}:{status}",
    )


# Shared non-AI committer path for initial seeding/manual injections.
def commit_non_ai_mutation_side_effects(
    *,
    session: TrainerSession,
    event_kind: str,
    correlation_id: str | None,
    worker_kind: str,
    domains: list[str] | None = None,
    source_call_id: str | None = None,
) -> None:
    if event_kind in {
        "problem",
        "assessment_finding",
        "diagnostic_result",
        "resource",
        "disposition",
        "intervention",
        "initial_seed",
        "scenario_brief",
    }:
        recompute_active_recommendations(session=session, correlation_id=correlation_id)
    _persist_patient_status_state(
        session=session,
        base_status=_current_patient_status_payload(session),
        source=EventSource.SYSTEM,
    )
    refresh_runtime_projection(session=session, correlation_id=correlation_id)
    record_patch_evaluation_summary(
        session=session,
        correlation_id=correlation_id,
        summary={
            "worker_kind": worker_kind,
            "domains": list(domains or []),
            "driver_reason_kinds": [event_kind],
            "driver_intervention_ids": [],
            "source_call_id": source_call_id or "",
            "correlation_id": correlation_id or "",
            "accepted": [{"event_kind": event_kind}],
            "normalized": [],
            "rejected": [],
        },
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

    Creates a new superseding ScenarioBrief event and refreshes derived views.
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

    emit_runtime_event(
        session=session,
        event_type=outbox_events.SIMULATION_BRIEF_UPDATED,
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
        idempotency_key=f"{outbox_events.SIMULATION_BRIEF_UPDATED}:{new_brief.id}",
    )
    commit_non_ai_mutation_side_effects(
        session=session,
        event_kind="scenario_brief",
        correlation_id=correlation_id,
        worker_kind="scenario_brief",
        domains=["scenario_brief"],
        source_call_id=None,
    )
    return new_brief


# ── Guard framework helpers ─────────────────────────────────────────────


def _sync_guard_pause(simulation_id: int, pause_reason: str = "manual") -> None:
    """Sync the guard SessionPresence when TrainerLab pauses a session.

    Called from ``pause_session()`` and from guard-initiated autopause.
    """
    try:
        from apps.guards.enums import GuardState, PauseReason
        from apps.guards.models import SessionPresence

        presence = SessionPresence.objects.filter(simulation_id=simulation_id).first()
        if presence is None:
            return

        reason_map = {
            "manual": (GuardState.PAUSED_MANUAL, PauseReason.MANUAL),
            "inactivity": (GuardState.PAUSED_INACTIVITY, PauseReason.INACTIVITY),
            "runtime_cap": (GuardState.PAUSED_RUNTIME_CAP, PauseReason.RUNTIME_CAP),
        }
        guard_state, mapped_reason = reason_map.get(
            pause_reason,
            (GuardState.PAUSED_MANUAL, PauseReason.MANUAL),
        )

        # Skip if guard framework has already set a non-runnable state —
        # the guard is authoritative and we must not overwrite it.
        from apps.guards.enums import NON_RUNNABLE_STATES

        if presence.guard_state in NON_RUNNABLE_STATES:
            return

        from django.utils import timezone as tz

        now = tz.now()
        presence.guard_state = guard_state
        presence.pause_reason = mapped_reason
        presence.paused_at = now
        presence.engine_runnable = False
        presence.save(
            update_fields=[
                "guard_state",
                "pause_reason",
                "paused_at",
                "engine_runnable",
                "modified_at",
            ]
        )
    except Exception:
        logger.exception("trainerlab.guard_sync_pause_failed", simulation_id=simulation_id)
