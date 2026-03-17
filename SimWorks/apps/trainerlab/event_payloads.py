from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from functools import lru_cache
from typing import Any

from .injury_dictionary import get_injury_dictionary_choices
from .intervention_dictionary import get_intervention_label, get_intervention_site_label
from .models import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    Problem,
    PulseAssessment,
    RecommendedIntervention,
    RespiratoryRate,
    ScenarioBrief,
    SimulationNote,
)

__all__ = [
    "enrich_summary_payload",
    "enrich_trainer_payload",
    "serialize_cause_snapshot",
    "serialize_domain_event",
    "serialize_intervention_summary",
    "serialize_problem_snapshot",
    "serialize_recommendation_summary",
]


@lru_cache(maxsize=1)
def _injury_label_maps() -> dict[str, dict[str, str]]:
    choices = get_injury_dictionary_choices()
    return {
        "march_category": dict(choices["categories"]),
        "injury_location": dict(choices["regions"]),
        "injury_kind": dict(choices["kinds"]),
    }


def _event_timestamp_iso(obj: Any) -> str | None:
    timestamp = getattr(obj, "timestamp", None)
    if timestamp is None:
        return None
    return timestamp.astimezone(UTC).isoformat()


def _datetime_iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _enrich_injury_labels(payload: dict[str, Any]) -> None:
    injury_maps = _injury_label_maps()
    for field_name, label_field in (
        ("march_category", "march_category_label"),
        ("injury_location", "injury_location_label"),
        ("injury_kind", "injury_kind_label"),
    ):
        raw_value = payload.get(field_name)
        if not isinstance(raw_value, str):
            continue
        label = injury_maps[field_name].get(raw_value.strip())
        if label:
            payload[label_field] = label


def _enrich_structured_intervention(payload: dict[str, Any]) -> bool:
    raw_type = payload.get("kind") or payload.get("intervention_type")
    if not isinstance(raw_type, str) or not raw_type:
        return False
    try:
        payload["title"] = payload.get("title") or get_intervention_label(raw_type)
        payload["intervention_label"] = get_intervention_label(raw_type)
    except ValueError:
        return False

    raw_site = payload.get("site_code")
    if isinstance(raw_site, str) and raw_site:
        try:
            payload["site_label"] = get_intervention_site_label(raw_type, raw_site)
        except ValueError:
            pass
    return True


def enrich_trainer_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    enriched = dict(payload or {})
    _enrich_injury_labels(enriched)
    _enrich_structured_intervention(enriched)
    return enriched


def _base_domain_event_payload(obj: Any) -> dict[str, Any]:
    return {
        "simulation_id": obj.simulation_id,
        "domain_event_id": obj.id,
        "domain_event_type": type(obj).__name__,
        "source": obj.source,
        "supersedes_event_id": getattr(obj, "supersedes_id", None),
        "timestamp": _event_timestamp_iso(obj),
    }


def _serialize_pulse_event(obj: PulseAssessment) -> dict[str, Any]:
    return {
        **_base_domain_event_payload(obj),
        "event_kind": "pulse_assessment",
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
    }


def _serialize_vital_event(obj: Any) -> dict[str, Any]:
    if isinstance(obj, HeartRate):
        vital_type = "heart_rate"
    elif isinstance(obj, RespiratoryRate):
        vital_type = "respiratory_rate"
    elif isinstance(obj, SPO2):
        vital_type = "spo2"
    elif isinstance(obj, ETCO2):
        vital_type = "etco2"
    elif isinstance(obj, BloodGlucoseLevel):
        vital_type = "blood_glucose"
    elif isinstance(obj, BloodPressure):
        vital_type = "blood_pressure"
    else:
        vital_type = type(obj).__name__

    payload = {
        **_base_domain_event_payload(obj),
        "event_kind": "vital",
        "vital_type": vital_type,
        "min_value": getattr(obj, "min_value", None),
        "max_value": getattr(obj, "max_value", None),
        "lock_value": getattr(obj, "lock_value", None),
    }
    if isinstance(obj, BloodPressure):
        payload["min_value_diastolic"] = obj.min_value_diastolic
        payload["max_value_diastolic"] = obj.max_value_diastolic
    return payload


def serialize_recommendation_summary(obj: RecommendedIntervention) -> dict[str, Any]:
    target_cause_kind = None
    target_cause_id = None
    if obj.target_injury_id:
        target_cause_kind = "injury"
        target_cause_id = obj.target_injury_id
    elif obj.target_illness_id:
        target_cause_kind = "illness"
        target_cause_id = obj.target_illness_id
    elif obj.target_problem_id and obj.target_problem.cause_id:
        target_cause_kind = obj.target_problem.cause_kind
        target_cause_id = obj.target_problem.cause_id
    return enrich_trainer_payload(
        {
            "recommendation_id": obj.id,
            "kind": obj.kind,
            "code": obj.code,
            "slug": obj.slug,
            "title": obj.title,
            "display_name": obj.display_name,
            "target_problem_id": obj.target_problem_id,
            "target_cause_id": target_cause_id,
            "target_cause_kind": target_cause_kind,
            "recommendation_source": obj.recommendation_source,
            "validation_status": obj.validation_status,
            "normalized_kind": obj.normalized_kind,
            "normalized_code": obj.normalized_code,
            "rationale": obj.rationale,
            "priority": obj.priority,
            "site_code": obj.site_code,
            "warnings": list(obj.warnings_json or []),
            "contraindications": list(obj.contraindications_json or []),
        }
    )


def serialize_problem_snapshot(problem: Problem) -> dict[str, Any]:
    recommendations = list(
        getattr(problem, "_prefetched_objects_cache", {}).get("recommended_interventions", [])
    )
    if not recommendations and hasattr(problem, "recommended_interventions"):
        recommendations = list(problem.recommended_interventions.all())
    return enrich_trainer_payload(
        {
            "problem_id": problem.id,
            "kind": problem.kind,
            "code": problem.code,
            "slug": problem.slug,
            "title": problem.title,
            "display_name": problem.display_name,
            "description": problem.description,
            "severity": problem.severity,
            "march_category": problem.march_category,
            "anatomical_location": problem.anatomical_location,
            "laterality": problem.laterality,
            "status": problem.status,
            "treated_at": _datetime_iso(problem.treated_at),
            "controlled_at": _datetime_iso(problem.controlled_at),
            "resolved_at": _datetime_iso(problem.resolved_at),
            "cause_id": problem.cause_id,
            "cause_kind": problem.cause_kind,
            "recommended_interventions": [
                serialize_recommendation_summary(item) for item in recommendations
            ],
            "source": problem.source,
            "timestamp": _event_timestamp_iso(problem),
        }
    )


def serialize_cause_snapshot(cause: Injury | Illness) -> dict[str, Any]:
    recommended = list(
        getattr(cause, "_prefetched_objects_cache", {}).get("recommended_interventions", [])
    )
    if not recommended and hasattr(cause, "recommended_interventions"):
        recommended = list(cause.recommended_interventions.all())
    return enrich_trainer_payload(
        {
            "id": cause.id,
            "cause_kind": cause.cause_kind,
            "kind": cause.kind,
            "code": cause.code,
            "slug": cause.slug,
            "title": cause.title,
            "display_name": cause.display_name,
            "description": cause.description,
            "anatomical_location": cause.anatomical_location,
            "laterality": cause.laterality,
            "recommended_interventions": [
                serialize_recommendation_summary(item) for item in recommended
            ],
            "source": cause.source,
            "timestamp": _event_timestamp_iso(cause),
            "injury_location": getattr(cause, "injury_location", None),
            "injury_kind": getattr(cause, "injury_kind", None),
        }
    )


def serialize_intervention_summary(obj: Intervention) -> dict[str, Any]:
    return enrich_trainer_payload(
        {
            "intervention_id": obj.id,
            "kind": obj.intervention_type,
            "code": obj.intervention_type,
            "title": get_intervention_label(obj.intervention_type) if obj.intervention_type else "",
            "target_problem_id": obj.target_problem_id,
            "initiated_by_type": obj.initiated_by_type,
            "initiated_by_id": obj.initiated_by_id,
            "status": obj.status,
            "effectiveness": obj.effectiveness,
            "notes": obj.notes,
            "site_code": obj.site_code,
            "details": dict(obj.details_json or {}),
            "source": obj.source,
            "timestamp": _event_timestamp_iso(obj),
        }
    )


def _serialize_cause_event(obj: Injury | Illness) -> dict[str, Any]:
    payload = {
        **_base_domain_event_payload(obj),
        "event_kind": "cause",
        "id": obj.id,
        "cause_kind": obj.cause_kind,
        "kind": obj.kind,
        "code": obj.code,
        "slug": obj.slug,
        "title": obj.title,
        "display_name": obj.display_name,
        "description": obj.description,
        "anatomical_location": obj.anatomical_location,
        "laterality": obj.laterality,
    }
    if isinstance(obj, Injury):
        payload["injury_location"] = obj.injury_location
        payload["injury_kind"] = obj.injury_kind
    return payload


def _serialize_problem_event(obj: Problem) -> dict[str, Any]:
    return {
        **_base_domain_event_payload(obj),
        "event_kind": "problem",
        **serialize_problem_snapshot(obj),
    }


def _serialize_recommendation_event(obj: RecommendedIntervention) -> dict[str, Any]:
    return {
        **_base_domain_event_payload(obj),
        "event_kind": "recommended_intervention",
        **serialize_recommendation_summary(obj),
    }


def _serialize_intervention_event(obj: Intervention) -> dict[str, Any]:
    return {
        **_base_domain_event_payload(obj),
        "event_kind": "intervention",
        **serialize_intervention_summary(obj),
    }


def serialize_domain_event(
    obj: Any,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(obj, Problem):
        payload = _serialize_problem_event(obj)
    elif isinstance(obj, Injury | Illness):
        payload = _serialize_cause_event(obj)
    elif isinstance(obj, RecommendedIntervention):
        payload = _serialize_recommendation_event(obj)
    elif isinstance(obj, Intervention):
        payload = _serialize_intervention_event(obj)
    elif isinstance(obj, ScenarioBrief):
        payload = {
            **_base_domain_event_payload(obj),
            "event_kind": "scenario_brief",
            "read_aloud_brief": obj.read_aloud_brief,
            "environment": obj.environment,
            "location_overview": obj.location_overview,
            "threat_context": obj.threat_context,
            "evacuation_options": obj.evacuation_options,
            "evacuation_time": obj.evacuation_time,
            "special_considerations": obj.special_considerations,
        }
    elif isinstance(obj, SimulationNote):
        payload = {
            **_base_domain_event_payload(obj),
            "event_kind": "note",
            "content": obj.content,
        }
    elif isinstance(obj, PulseAssessment):
        payload = _serialize_pulse_event(obj)
    else:
        payload = _serialize_vital_event(obj)

    if extra:
        payload.update(dict(extra))
    return enrich_trainer_payload(payload)


def enrich_summary_payload(summary_payload: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(summary_payload)

    timeline = []
    for item in enriched.get("timeline_highlights", []):
        timeline_item = dict(item)
        timeline_item["payload"] = enrich_trainer_payload(item.get("payload"))
        timeline.append(timeline_item)
    if timeline:
        enriched["timeline_highlights"] = timeline

    command_log = []
    for item in enriched.get("command_log", []):
        command_item = dict(item)
        command_item["payload"] = enrich_trainer_payload(item.get("payload"))
        command_log.append(command_item)
    if command_log:
        enriched["command_log"] = command_log

    return enriched
