from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from functools import lru_cache
from typing import Any

from .injury_dictionary import get_injury_dictionary_choices
from .intervention_dictionary import (
    get_intervention_label,
    get_intervention_site_label,
)
from .models import (
    ETCO2,
    SPO2,
    ABCEvent,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    PulseAssessment,
    RespiratoryRate,
    ScenarioBrief,
    SimulationNote,
)

__all__ = [
    "enrich_summary_payload",
    "enrich_trainer_payload",
    "serialize_domain_event",
]


@lru_cache(maxsize=1)
def _injury_label_maps() -> dict[str, dict[str, str]]:
    choices = get_injury_dictionary_choices()
    return {
        "injury_category": dict(choices["categories"]),
        "injury_location": dict(choices["regions"]),
        "injury_kind": dict(choices["kinds"]),
    }


def _event_timestamp_iso(obj: Any) -> str | None:
    timestamp = getattr(obj, "timestamp", None)
    if timestamp is None:
        return None
    return timestamp.astimezone(UTC).isoformat()


def _enrich_injury_labels(payload: dict[str, Any]) -> None:
    injury_maps = _injury_label_maps()
    for field_name, label_field in (
        ("injury_category", "injury_category_label"),
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
    raw_type = payload.get("intervention_type")
    if not isinstance(raw_type, str):
        return False

    try:
        payload["intervention_label"] = get_intervention_label(raw_type)
    except ValueError:
        return False

    raw_site = payload.get("site_code")
    if isinstance(raw_site, str):
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


def _base_domain_event_payload(obj: ABCEvent) -> dict[str, Any]:
    return {
        "simulation_id": obj.simulation_id,
        "domain_event_id": obj.id,
        "domain_event_type": type(obj).__name__,
        "source": obj.source,
        "supersedes_event_id": obj.supersedes_event_id,
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


def _serialize_vital_event(obj: ABCEvent) -> dict[str, Any]:
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


def serialize_domain_event(
    obj: ABCEvent,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(obj, Injury):
        payload = {
            **_base_domain_event_payload(obj),
            "event_kind": "injury",
            "condition_kind": "injury",
            "injury_id": obj.id,
            "parent_injury_id": obj.parent_injury_id,
            "injury_category": obj.injury_category,
            "injury_location": obj.injury_location,
            "injury_kind": obj.injury_kind,
            "injury_description": obj.injury_description,
            "is_treated": obj.is_treated,
            "is_resolved": obj.is_resolved,
        }
    elif isinstance(obj, Illness):
        payload = {
            **_base_domain_event_payload(obj),
            "event_kind": "illness",
            "condition_kind": "illness",
            "illness_id": obj.id,
            "name": obj.name,
            "description": obj.description,
            "severity": obj.severity,
            "is_resolved": obj.is_resolved,
        }
    elif isinstance(obj, Intervention):
        payload = {
            **_base_domain_event_payload(obj),
            "event_kind": "intervention",
            "intervention_id": obj.id,
            "intervention_type": obj.intervention_type,
            "site_code": obj.site_code,
            "target_injury_id": obj.target_injury_id,
            "status": obj.status,
            "effectiveness": obj.effectiveness,
            "notes": obj.notes,
            "details": dict(obj.details_json or {}),
        }
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
