from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from pydantic import Field

from config.logging import get_logger
from orchestrai.types import StrictBaseModel

from .event_payloads import (
    serialize_assessment_finding_summary,
    serialize_cause_snapshot,
    serialize_diagnostic_result_summary,
    serialize_disposition_state_summary,
    serialize_intervention_summary,
    serialize_problem_snapshot,
    serialize_recommendation_summary,
    serialize_resource_state_summary,
)
from .models import (
    ETCO2,
    SPO2,
    AssessmentFinding,
    BloodGlucoseLevel,
    BloodPressure,
    DiagnosticResult,
    DispositionState,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    PatientStatusState,
    Problem,
    PulseAssessment,
    RecommendedIntervention,
    ResourceState,
    RespiratoryRate,
    RuntimeEvent,
    ScenarioBrief as ScenarioBriefModel,
    SessionStatus,
    TrainerSession,
)
from .schemas.shared import RuntimeInstructorIntent, RuntimePatientStatus, ScenarioBrief

logger = get_logger(__name__)

BUILDER_VERSION = "v1"
SCHEMA_VERSION = "v1"
DEFAULT_EVENT_TIMELINE_LIMIT = 100

VITAL_TYPE_MODEL_MAP = {
    "heart_rate": HeartRate,
    "respiratory_rate": RespiratoryRate,
    "spo2": SPO2,
    "etco2": ETCO2,
    "blood_glucose": BloodGlucoseLevel,
    "blood_pressure": BloodPressure,
}


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


def compute_active_elapsed_seconds(
    *,
    session: TrainerSession,
    runtime_state: dict[str, Any],
    now: datetime | None = None,
) -> int:
    now = now or timezone.now()
    elapsed = int(runtime_state.get("active_elapsed_seconds", 0) or 0)
    anchor = _parse_iso_datetime(runtime_state.get("active_elapsed_anchor_started_at"))
    if session.status == SessionStatus.RUNNING and anchor is not None:
        elapsed += max(0, int((now - anchor).total_seconds()))
    return elapsed


class SnapshotCacheStatus(StrictBaseModel):
    status: Literal["disabled", "missing", "stale", "available"] = "disabled"
    authoritative: bool = False
    source: str = "disabled"
    state_revision: int | None = None
    legacy_keys_present: list[str] = Field(default_factory=list)


class EventTimelineEntry(StrictBaseModel):
    event_id: str
    event_type: str
    created_at: datetime
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventTimeline(StrictBaseModel):
    events: list[EventTimelineEntry] = Field(default_factory=list)
    total_events: int = 0


class ScenarioSnapshot(StrictBaseModel):
    causes: list[dict[str, Any]] = Field(default_factory=list)
    problems: list[dict[str, Any]] = Field(default_factory=list)
    recommended_interventions: list[dict[str, Any]] = Field(default_factory=list)
    interventions: list[dict[str, Any]] = Field(default_factory=list)
    assessment_findings: list[dict[str, Any]] = Field(default_factory=list)
    diagnostic_results: list[dict[str, Any]] = Field(default_factory=list)
    resources: list[dict[str, Any]] = Field(default_factory=list)
    disposition: dict[str, Any] | None = None
    vitals: list[dict[str, Any]] = Field(default_factory=list)
    pulses: list[dict[str, Any]] = Field(default_factory=list)
    patient_status: RuntimePatientStatus = Field(default_factory=RuntimePatientStatus)
    scenario_brief: ScenarioBrief | None = None


class RuntimeSnapshot(StrictBaseModel):
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    phase: str = ""
    state_revision: int = 0
    active_elapsed_seconds: int = 0
    tick_count: int = 0
    tick_interval_seconds: int = 15
    next_tick_at: datetime | None = None
    runtime_processing: bool = False
    pending_runtime_reasons: list[dict[str, Any]] = Field(default_factory=list)
    currently_processing_reasons: list[dict[str, Any]] = Field(default_factory=list)
    ai_plan: RuntimeInstructorIntent = Field(default_factory=RuntimeInstructorIntent)
    ai_rationale_notes: list[str] = Field(default_factory=list)
    llm_conditions_check: list[dict[str, Any]] = Field(default_factory=list)
    last_runtime_error: str = ""
    last_ai_tick_at: datetime | None = None
    last_runtime_enqueued_at: str | None = None
    last_runtime_completed_at: str | None = None
    control_plane_debug: dict[str, Any] = Field(default_factory=dict)
    request_metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioStateSummary(StrictBaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    latest_event_ids: dict[str, int | None] = Field(default_factory=dict)
    latest_timestamps: dict[str, str | None] = Field(default_factory=dict)


class RuntimeStateSummary(StrictBaseModel):
    phase: str = ""
    state_revision: int = 0
    runtime_processing: bool = False
    pending_reason_count: int = 0
    currently_processing_count: int = 0
    last_runtime_error: str = ""
    legacy_keys_present: list[str] = Field(default_factory=list)
    raw_runtime_state: dict[str, Any] = Field(default_factory=dict)


class WatchSnapshot(StrictBaseModel):
    scenario_state_summary: ScenarioStateSummary
    runtime_state_summary: RuntimeStateSummary
    snapshot_cache: SnapshotCacheStatus


class TrainerAgentViewModelMetadata(StrictBaseModel):
    builder_version: str = BUILDER_VERSION
    schema_version: str = SCHEMA_VERSION
    snapshot_cache: SnapshotCacheStatus


class TrainerAgentViewModel(StrictBaseModel):
    simulation_id: int
    session_id: int
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    scenario_snapshot: ScenarioSnapshot
    runtime_snapshot: RuntimeSnapshot
    event_timeline: EventTimeline
    trigger_reasons: list[dict[str, Any]] = Field(default_factory=list)
    metadata: TrainerAgentViewModelMetadata


class TrainerRestMetadata(StrictBaseModel):
    builder_version: str = BUILDER_VERSION
    schema_version: str = SCHEMA_VERSION
    snapshot_cache: SnapshotCacheStatus
    event_timeline_count: int = 0


class TrainerRestViewModel(StrictBaseModel):
    simulation_id: int
    session_id: int
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    scenario_snapshot: ScenarioSnapshot
    runtime_snapshot: RuntimeSnapshot
    event_timeline: EventTimeline
    metadata: TrainerRestMetadata


class TrainerWatchViewModel(StrictBaseModel):
    simulation_id: int
    session_id: int
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    watch_snapshot: WatchSnapshot
    scenario_snapshot: ScenarioSnapshot
    runtime_snapshot: RuntimeSnapshot
    event_timeline: EventTimeline


@dataclass(frozen=True)
class TrainerEngineAggregate:
    session: TrainerSession
    runtime_state: dict[str, Any]
    injuries: tuple[Injury, ...]
    illnesses: tuple[Illness, ...]
    problems: tuple[Problem, ...]
    recommendations: tuple[RecommendedIntervention, ...]
    interventions: tuple[Intervention, ...]
    assessment_findings: tuple[AssessmentFinding, ...]
    diagnostic_results: tuple[DiagnosticResult, ...]
    resources: tuple[ResourceState, ...]
    disposition: DispositionState | None
    scenario_brief: ScenarioBriefModel | None
    patient_status: PatientStatusState | None
    vitals_by_type: dict[str, Any]
    pulses: tuple[PulseAssessment, ...]
    runtime_events: tuple[RuntimeEvent, ...]
    snapshot_cache: SnapshotCacheStatus


def load_trainer_engine_aggregate(
    *,
    session: TrainerSession | None = None,
    simulation_id: int | None = None,
    event_limit: int = DEFAULT_EVENT_TIMELINE_LIMIT,
    runtime_state_override: dict[str, Any] | None = None,
) -> TrainerEngineAggregate:
    if session is None and simulation_id is None:
        raise ValueError("Either session or simulation_id is required")

    if session is None:
        session = (
            TrainerSession.objects.select_related("simulation")
            .filter(simulation_id=simulation_id)
            .first()
        )
    else:
        session = TrainerSession.objects.select_related("simulation").get(pk=session.pk)

    if session is None:
        raise TrainerSession.DoesNotExist("Trainer session not found")

    simulation = session.simulation
    runtime_state = (
        dict(runtime_state_override)
        if runtime_state_override is not None
        else dict(session.runtime_state_json or {})
    )

    recommendations = tuple(
        RecommendedIntervention.objects.select_related(
            "target_problem",
            "target_injury",
            "target_illness",
        )
        .filter(simulation=simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    problems = tuple(
        Problem.objects.select_related("cause_injury", "cause_illness")
        .filter(simulation=simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    injuries = tuple(
        Injury.objects.filter(simulation=simulation, is_active=True).order_by("timestamp", "id")
    )
    illnesses = tuple(
        Illness.objects.prefetch_related("recommended_interventions")
        .filter(simulation=simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    interventions = tuple(
        Intervention.objects.select_related("target_problem")
        .filter(simulation=simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    assessment_findings = tuple(
        AssessmentFinding.objects.select_related("target_problem")
        .filter(simulation=simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    diagnostic_results = tuple(
        DiagnosticResult.objects.select_related("target_problem")
        .filter(simulation=simulation, is_active=True)
        .order_by("timestamp", "id")
    )
    resources = tuple(
        ResourceState.objects.filter(simulation=simulation, is_active=True).order_by(
            "timestamp", "id"
        )
    )
    disposition = (
        DispositionState.objects.filter(simulation=simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    scenario_brief = (
        ScenarioBriefModel.objects.filter(simulation=simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    patient_status = (
        PatientStatusState.objects.filter(simulation=simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    pulses = tuple(
        PulseAssessment.objects.filter(simulation=simulation, is_active=True).order_by("location")
    )
    vitals_by_type = {
        vital_type: (
            model.objects.filter(simulation=simulation, is_active=True)
            .order_by("-timestamp", "-id")
            .first()
        )
        for vital_type, model in VITAL_TYPE_MODEL_MAP.items()
    }
    runtime_events = tuple(
        RuntimeEvent.objects.filter(session=session).order_by("-created_at", "-id")[:event_limit]
    )

    legacy_keys_present = [
        key
        for key in ("current_snapshot", "scenario_brief", "snapshot_annotations")
        if runtime_state.get(key) not in (None, "", [], {})
    ]
    snapshot_cache = SnapshotCacheStatus(
        status="disabled",
        authoritative=False,
        source="disabled",
        state_revision=int(runtime_state.get("state_revision", 0) or 0),
        legacy_keys_present=legacy_keys_present,
    )

    return TrainerEngineAggregate(
        session=session,
        runtime_state=runtime_state,
        injuries=injuries,
        illnesses=illnesses,
        problems=problems,
        recommendations=recommendations,
        interventions=interventions,
        assessment_findings=assessment_findings,
        diagnostic_results=diagnostic_results,
        resources=resources,
        disposition=disposition,
        scenario_brief=scenario_brief,
        patient_status=patient_status,
        vitals_by_type=vitals_by_type,
        pulses=pulses,
        runtime_events=runtime_events,
        snapshot_cache=snapshot_cache,
    )


def build_scenario_snapshot(aggregate: TrainerEngineAggregate) -> ScenarioSnapshot:
    intervention_effects = dict(aggregate.runtime_state.get("intervention_effects") or {})
    _seed_recommendation_prefetch_cache(aggregate)
    causes = [
        serialize_cause_snapshot(item)
        for item in sorted(
            [*aggregate.injuries, *aggregate.illnesses],
            key=lambda item: (item.timestamp, item.id),
        )
    ]
    scenario_snapshot = ScenarioSnapshot(
        causes=causes,
        problems=[serialize_problem_snapshot(problem) for problem in aggregate.problems],
        recommended_interventions=[
            serialize_recommendation_summary(item) for item in aggregate.recommendations
        ],
        interventions=[
            _serialize_intervention_with_effects(item, intervention_effects=intervention_effects)
            for item in aggregate.interventions
        ],
        assessment_findings=[
            serialize_assessment_finding_summary(item) for item in aggregate.assessment_findings
        ],
        diagnostic_results=[
            serialize_diagnostic_result_summary(item) for item in aggregate.diagnostic_results
        ],
        resources=[serialize_resource_state_summary(item) for item in aggregate.resources],
        disposition=(
            serialize_disposition_state_summary(aggregate.disposition)
            if aggregate.disposition is not None
            else None
        ),
        vitals=[
            _serialize_vital(vital_type, vital)
            for vital_type, vital in aggregate.vitals_by_type.items()
            if vital is not None
        ],
        pulses=[_serialize_pulse(item) for item in aggregate.pulses],
        patient_status=_build_patient_status_snapshot(aggregate),
        scenario_brief=(
            ScenarioBrief.model_validate(
                {
                    "read_aloud_brief": aggregate.scenario_brief.read_aloud_brief,
                    "environment": aggregate.scenario_brief.environment,
                    "location_overview": aggregate.scenario_brief.location_overview,
                    "threat_context": aggregate.scenario_brief.threat_context,
                    "evacuation_options": aggregate.scenario_brief.evacuation_options,
                    "evacuation_time": aggregate.scenario_brief.evacuation_time,
                    "special_considerations": aggregate.scenario_brief.special_considerations,
                }
            )
            if aggregate.scenario_brief is not None
            else None
        ),
    )
    logger.debug(
        "trainerlab.scenario_snapshot.built",
        session_id=aggregate.session.id,
        simulation_id=aggregate.session.simulation_id,
        state_revision=int(aggregate.runtime_state.get("state_revision", 0) or 0),
    )
    return scenario_snapshot


def build_runtime_snapshot(aggregate: TrainerEngineAggregate) -> RuntimeSnapshot:
    runtime_state = aggregate.runtime_state
    next_tick_at = None
    if aggregate.session.last_ai_tick_at is not None and aggregate.session.tick_interval_seconds:
        next_tick_at = aggregate.session.last_ai_tick_at + timedelta(
            seconds=aggregate.session.tick_interval_seconds
        )

    runtime_snapshot = RuntimeSnapshot(
        status=aggregate.session.status,
        phase=str(runtime_state.get("phase") or aggregate.session.status),
        state_revision=int(runtime_state.get("state_revision", 0) or 0),
        active_elapsed_seconds=compute_active_elapsed_seconds(
            session=aggregate.session,
            runtime_state=runtime_state,
        ),
        tick_count=int(runtime_state.get("tick_count", 0) or 0),
        tick_interval_seconds=aggregate.session.tick_interval_seconds,
        next_tick_at=next_tick_at,
        runtime_processing=bool(runtime_state.get("runtime_processing")),
        pending_runtime_reasons=list(runtime_state.get("pending_runtime_reasons") or []),
        currently_processing_reasons=list(runtime_state.get("currently_processing_reasons") or []),
        ai_plan=RuntimeInstructorIntent.model_validate(runtime_state.get("ai_plan") or {}),
        ai_rationale_notes=list(runtime_state.get("ai_rationale_notes") or []),
        llm_conditions_check=list(runtime_state.get("llm_conditions_check") or []),
        last_runtime_error=str(runtime_state.get("last_runtime_error") or ""),
        last_ai_tick_at=aggregate.session.last_ai_tick_at,
        last_runtime_enqueued_at=runtime_state.get("last_runtime_enqueued_at"),
        last_runtime_completed_at=runtime_state.get("last_runtime_completed_at"),
        control_plane_debug=dict(runtime_state.get("control_plane_debug") or {}),
        request_metadata=dict(
            (runtime_state.get("control_plane_debug") or {}).get("last_request_profile") or {}
        ),
    )
    logger.debug(
        "trainerlab.runtime_snapshot.built",
        session_id=aggregate.session.id,
        simulation_id=aggregate.session.simulation_id,
        state_revision=runtime_snapshot.state_revision,
    )
    return runtime_snapshot


def build_event_timeline(aggregate: TrainerEngineAggregate) -> EventTimeline:
    events = [
        EventTimelineEntry(
            event_id=str(item.id),
            event_type=item.event_type,
            created_at=item.created_at,
            correlation_id=item.correlation_id,
            payload=dict(item.payload or {}),
        )
        for item in aggregate.runtime_events
    ]
    return EventTimeline(events=events, total_events=len(events))


def build_watch_snapshot(aggregate: TrainerEngineAggregate) -> WatchSnapshot:
    latest_event_ids = {
        "scenario_brief": aggregate.scenario_brief.id if aggregate.scenario_brief else None,
        "patient_status": aggregate.patient_status.id if aggregate.patient_status else None,
        "disposition": aggregate.disposition.id if aggregate.disposition else None,
    }
    latest_timestamps = {
        "scenario_brief": _iso_or_none(getattr(aggregate.scenario_brief, "timestamp", None)),
        "patient_status": _iso_or_none(getattr(aggregate.patient_status, "timestamp", None)),
        "disposition": _iso_or_none(getattr(aggregate.disposition, "timestamp", None)),
        "latest_runtime_event": _iso_or_none(
            aggregate.runtime_events[0].created_at if aggregate.runtime_events else None
        ),
    }
    return WatchSnapshot(
        scenario_state_summary=ScenarioStateSummary(
            counts={
                "causes": len(aggregate.injuries) + len(aggregate.illnesses),
                "problems": len(aggregate.problems),
                "recommended_interventions": len(aggregate.recommendations),
                "interventions": len(aggregate.interventions),
                "assessment_findings": len(aggregate.assessment_findings),
                "diagnostic_results": len(aggregate.diagnostic_results),
                "resources": len(aggregate.resources),
                "vitals": sum(
                    1 for vital in aggregate.vitals_by_type.values() if vital is not None
                ),
                "pulses": len(aggregate.pulses),
            },
            latest_event_ids=latest_event_ids,
            latest_timestamps=latest_timestamps,
        ),
        runtime_state_summary=RuntimeStateSummary(
            phase=str(aggregate.runtime_state.get("phase") or aggregate.session.status),
            state_revision=int(aggregate.runtime_state.get("state_revision", 0) or 0),
            runtime_processing=bool(aggregate.runtime_state.get("runtime_processing")),
            pending_reason_count=len(aggregate.runtime_state.get("pending_runtime_reasons") or []),
            currently_processing_count=len(
                aggregate.runtime_state.get("currently_processing_reasons") or []
            ),
            last_runtime_error=str(aggregate.runtime_state.get("last_runtime_error") or ""),
            legacy_keys_present=list(aggregate.snapshot_cache.legacy_keys_present),
            raw_runtime_state=dict(aggregate.runtime_state),
        ),
        snapshot_cache=aggregate.snapshot_cache,
    )


def build_trainer_agent_view_model(
    aggregate: TrainerEngineAggregate,
    *,
    reasons: list[dict[str, Any]] | None = None,
) -> TrainerAgentViewModel:
    scenario_snapshot = build_scenario_snapshot(aggregate)
    runtime_snapshot = build_runtime_snapshot(aggregate)
    event_timeline = build_event_timeline(aggregate)
    return TrainerAgentViewModel(
        simulation_id=aggregate.session.simulation_id,
        session_id=aggregate.session.id,
        status=aggregate.session.status,
        scenario_snapshot=scenario_snapshot,
        runtime_snapshot=runtime_snapshot,
        event_timeline=event_timeline,
        trigger_reasons=list(reasons or []),
        metadata=TrainerAgentViewModelMetadata(snapshot_cache=aggregate.snapshot_cache),
    )


def build_trainer_rest_view_model(aggregate: TrainerEngineAggregate) -> TrainerRestViewModel:
    scenario_snapshot = build_scenario_snapshot(aggregate)
    runtime_snapshot = build_runtime_snapshot(aggregate)
    event_timeline = build_event_timeline(aggregate)
    return TrainerRestViewModel(
        simulation_id=aggregate.session.simulation_id,
        session_id=aggregate.session.id,
        status=aggregate.session.status,
        scenario_snapshot=scenario_snapshot,
        runtime_snapshot=runtime_snapshot,
        event_timeline=event_timeline,
        metadata=TrainerRestMetadata(
            snapshot_cache=aggregate.snapshot_cache,
            event_timeline_count=event_timeline.total_events,
        ),
    )


def build_trainer_watch_view_model(aggregate: TrainerEngineAggregate) -> TrainerWatchViewModel:
    return TrainerWatchViewModel(
        simulation_id=aggregate.session.simulation_id,
        session_id=aggregate.session.id,
        status=aggregate.session.status,
        watch_snapshot=build_watch_snapshot(aggregate),
        scenario_snapshot=build_scenario_snapshot(aggregate),
        runtime_snapshot=build_runtime_snapshot(aggregate),
        event_timeline=build_event_timeline(aggregate),
    )


def _serialize_intervention_with_effects(
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
        "min_value": obj.min_value,
        "max_value": obj.max_value,
        "lock_value": obj.lock_value,
        "timestamp": _iso_or_none(obj.timestamp),
        "source": obj.source,
    }
    if vital_type == "blood_pressure":
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


def _build_patient_status_snapshot(aggregate: TrainerEngineAggregate) -> RuntimePatientStatus:
    if aggregate.patient_status is not None:
        return RuntimePatientStatus.model_validate(
            {
                "avpu": aggregate.patient_status.avpu or None,
                "respiratory_distress": aggregate.patient_status.respiratory_distress,
                "hemodynamic_instability": aggregate.patient_status.hemodynamic_instability,
                "impending_pneumothorax": aggregate.patient_status.impending_pneumothorax,
                "tension_pneumothorax": aggregate.patient_status.tension_pneumothorax,
                "narrative": aggregate.patient_status.narrative,
                "teaching_flags": list(aggregate.patient_status.teaching_flags or []),
            }
        )
    legacy_status = dict(
        (aggregate.runtime_state.get("snapshot_annotations") or {}).get("patient_status") or {}
    )
    if legacy_status:
        logger.debug(
            "trainerlab.patient_status.legacy_fallback_used",
            session_id=aggregate.session.id,
            simulation_id=aggregate.session.simulation_id,
        )
    return RuntimePatientStatus.model_validate(
        _derive_patient_status_from_problem_kinds(
            active_kinds={problem.kind for problem in aggregate.problems},
            base_status=legacy_status,
        )
    )


def _seed_recommendation_prefetch_cache(aggregate: TrainerEngineAggregate) -> None:
    recommendations_by_problem_id: dict[int, list[RecommendedIntervention]] = {}
    recommendations_by_cause_key: dict[tuple[str, int], list[RecommendedIntervention]] = {}

    for recommendation in aggregate.recommendations:
        if recommendation.target_problem_id is not None:
            recommendations_by_problem_id.setdefault(recommendation.target_problem_id, []).append(
                recommendation
            )
        if recommendation.target_injury_id is not None:
            recommendations_by_cause_key.setdefault(
                ("injury", recommendation.target_injury_id), []
            ).append(recommendation)
        if recommendation.target_illness_id is not None:
            recommendations_by_cause_key.setdefault(
                ("illness", recommendation.target_illness_id), []
            ).append(recommendation)

    for problem in aggregate.problems:
        prefetched = dict(getattr(problem, "_prefetched_objects_cache", {}))
        prefetched["recommended_interventions"] = list(
            recommendations_by_problem_id.get(problem.id, [])
        )
        problem._prefetched_objects_cache = prefetched

    for injury in aggregate.injuries:
        prefetched = dict(getattr(injury, "_prefetched_objects_cache", {}))
        prefetched["recommended_interventions"] = list(
            recommendations_by_cause_key.get(("injury", injury.id), [])
        )
        injury._prefetched_objects_cache = prefetched

    for illness in aggregate.illnesses:
        prefetched = dict(getattr(illness, "_prefetched_objects_cache", {}))
        prefetched["recommended_interventions"] = list(
            recommendations_by_cause_key.get(("illness", illness.id), [])
        )
        illness._prefetched_objects_cache = prefetched


def _derive_patient_status_from_problem_kinds(
    *,
    active_kinds: set[str],
    base_status: dict[str, Any] | None,
) -> dict[str, Any]:
    patient_status = dict(base_status or {})
    patient_status["respiratory_distress"] = bool(
        patient_status.get("respiratory_distress")
        or {"respiratory_distress", "tension_pneumothorax", "hypoxia"} & active_kinds
    )
    patient_status["hemodynamic_instability"] = bool(
        patient_status.get("hemodynamic_instability")
        or {"hemorrhage", "hypoperfusion_shock"} & active_kinds
    )
    patient_status["tension_pneumothorax"] = bool(
        patient_status.get("tension_pneumothorax") or "tension_pneumothorax" in active_kinds
    )
    patient_status["impending_pneumothorax"] = bool(
        patient_status.get("impending_pneumothorax")
        or ("open_chest_wound" in active_kinds and "tension_pneumothorax" not in active_kinds)
    )
    if not patient_status.get("narrative"):
        if "hypoperfusion_shock" in active_kinds:
            patient_status["narrative"] = (
                "Patient is decompensating with evolving shock physiology."
            )
        elif "tension_pneumothorax" in active_kinds:
            patient_status["narrative"] = (
                "Patient is in critical respiratory compromise with tension physiology."
            )
        elif "infectious_process" in active_kinds:
            patient_status["narrative"] = "Patient remains ill with an active infectious process."
        else:
            patient_status["narrative"] = "Patient status is being actively reassessed."
    patient_status.setdefault("teaching_flags", [])
    return patient_status
