from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from django.conf import settings
from django.utils import timezone
import tiktoken

from apps.trainerlab.models import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Intervention,
    Problem,
    ResourceState,
    RespiratoryRate,
    TrainerSession,
)
from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.components.instructions.collector import collect_instructions

DEFAULT_RUNTIME_MAX_BATCH_REASONS = 8
DEFAULT_RUNTIME_MAX_PROMPT_TOKENS = 7000
DEFAULT_RUNTIME_MAX_OUTPUT_TOKENS = 1200

_TEXT_LIMITS_BY_TRIM = {
    0: {"content": 320, "note": 240, "prompt": 320},
    1: {"content": 220, "note": 180, "prompt": 220},
    2: {"content": 140, "note": 120, "prompt": 140},
    3: {"content": 96, "note": 96, "prompt": 96},
}
_LOW_PRIORITY_CONTEXT_FIELDS = (
    "scenario_context",
    "recommendation_summary",
    "diagnostic_summary",
    "resource_summary",
    "disposition_summary",
)
_VITAL_MODEL_MAP = {
    "heart_rate": HeartRate,
    "respiratory_rate": RespiratoryRate,
    "spo2": SPO2,
    "etco2": ETCO2,
    "blood_glucose": BloodGlucoseLevel,
    "blood_pressure": BloodPressure,
}


@dataclass(frozen=True)
class RuntimeBudgetResult:
    runtime_llm_context: dict[str, Any]
    runtime_reasons: list[dict[str, Any]]
    metrics: dict[str, Any]
    allowed: bool
    error_code: str | None = None
    error_message: str | None = None


def get_runtime_max_batch_reasons() -> int:
    value = getattr(
        settings,
        "TRAINERLAB_RUNTIME_MAX_BATCH_REASONS",
        DEFAULT_RUNTIME_MAX_BATCH_REASONS,
    )
    return max(1, int(value))


def get_runtime_max_prompt_tokens() -> int:
    value = getattr(
        settings,
        "TRAINERLAB_RUNTIME_MAX_PROMPT_TOKENS",
        DEFAULT_RUNTIME_MAX_PROMPT_TOKENS,
    )
    return max(1000, int(value))


def get_runtime_max_output_tokens() -> int:
    value = getattr(
        settings,
        "TRAINERLAB_RUNTIME_MAX_OUTPUT_TOKENS",
        DEFAULT_RUNTIME_MAX_OUTPUT_TOKENS,
    )
    return max(128, int(value))


def render_runtime_llm_context(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"))


def json_byte_length(value: Any) -> int:
    return len(render_runtime_llm_context(value).encode("utf-8"))


def compact_runtime_reasons(
    reasons: Sequence[dict[str, Any]] | None,
    *,
    max_reasons: int | None = None,
    trim_level: int = 0,
) -> list[dict[str, Any]]:
    max_reasons = max_reasons or get_runtime_max_batch_reasons()
    text_limits = _TEXT_LIMITS_BY_TRIM.get(trim_level, _TEXT_LIMITS_BY_TRIM[3])
    raw_reasons = list(reasons or [])
    compacted: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    coalesced_ticks: dict[str, dict[str, Any]] = {}

    for index, reason in enumerate(raw_reasons):
        reason_kind = str(reason.get("reason_kind") or "unknown")
        payload = dict(reason.get("payload") or {})

        if reason_kind in {"tick", "manual_tick"}:
            existing = coalesced_ticks.get(reason_kind)
            latest_created_at = reason.get("created_at")
            if existing is None:
                coalesced_ticks[reason_kind] = {
                    "reason_kind": reason_kind,
                    "count": 1,
                    "latest_created_at": latest_created_at,
                    "__priority": _runtime_reason_priority(reason),
                    "__order": index,
                }
            else:
                existing["count"] = int(existing.get("count", 0)) + 1
                existing["latest_created_at"] = latest_created_at or existing.get(
                    "latest_created_at"
                )
            continue

        dedupe_key = _runtime_reason_dedupe_key(reason)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        item = {
            "reason_kind": reason_kind,
            "__priority": _runtime_reason_priority(reason),
            "__order": index,
        }
        if reason.get("created_at"):
            item["created_at"] = reason["created_at"]

        if reason_kind.endswith("_recorded"):
            if payload.get("event_kind"):
                item["event_kind"] = payload.get("event_kind")
            if payload.get("domain_event_type"):
                item["domain_event_type"] = payload.get("domain_event_type")
            if payload.get("domain_event_id") is not None:
                item["domain_event_id"] = payload.get("domain_event_id")
            if payload.get("command_id"):
                item["command_id"] = payload.get("command_id")
            if reason_kind == "note_recorded" and payload.get("send_to_ai"):
                item["content"] = _truncate(payload.get("content"), text_limits["content"])
        elif reason_kind == "adjustment":
            for field in (
                "command_id",
                "target",
                "direction",
                "magnitude",
                "injury_event_id",
                "injury_region",
                "avpu_state",
                "intervention_code",
            ):
                if payload.get(field) not in (None, "", [], {}):
                    item[field] = payload.get(field)
            if payload.get("note"):
                item["note"] = _truncate(payload.get("note"), text_limits["note"])
        elif reason_kind == "steer_prompt":
            if payload.get("command_id"):
                item["command_id"] = payload.get("command_id")
            if payload.get("prompt"):
                item["prompt"] = _truncate(payload.get("prompt"), text_limits["prompt"])
        elif reason_kind == "preset_applied":
            if payload.get("preset_id") is not None:
                item["preset_id"] = payload.get("preset_id")
            if payload.get("title"):
                item["title"] = _truncate(payload.get("title"), 96)
            if payload.get("command_id"):
                item["command_id"] = payload.get("command_id")
        else:
            for field in ("command_id", "status"):
                if payload.get(field) not in (None, "", [], {}):
                    item[field] = payload.get(field)

        compacted.append(item)

    compacted.extend(coalesced_ticks.values())
    compacted.sort(key=lambda item: (-int(item["__priority"]), int(item["__order"])))
    compacted = compacted[:max_reasons]
    compacted.sort(key=lambda item: int(item["__order"]))
    for item in compacted:
        item.pop("__priority", None)
        item.pop("__order", None)
    return compacted


def project_runtime_llm_snapshot(
    session: TrainerSession,
    *,
    current_snapshot: dict[str, Any] | None,
    active_elapsed_seconds: int,
    trim_level: int = 0,
) -> dict[str, Any]:
    snapshot = dict(current_snapshot or {})
    now = timezone.now()
    active_problem_ages = {
        problem_id: max(0, int((now - timestamp).total_seconds()))
        for problem_id, timestamp in Problem.objects.filter(
            simulation=session.simulation,
            is_active=True,
        ).values_list("id", "timestamp")
    }
    active_intervention_ages = {
        intervention_id: max(0, int((now - timestamp).total_seconds()))
        for intervention_id, timestamp in Intervention.objects.filter(
            simulation=session.simulation,
            is_active=True,
        ).values_list("id", "timestamp")
    }

    active_causes = [
        _strip_empty(
            {
                "cause_id": cause.get("id"),
                "cause_kind": cause.get("cause_kind"),
                "kind": cause.get("kind"),
                "title": cause.get("title"),
                "anatomical_location": cause.get("anatomical_location"),
                "laterality": cause.get("laterality"),
            }
        )
        for cause in snapshot.get("causes", [])
    ]
    active_problems = [
        _strip_empty(
            {
                "problem_id": problem.get("problem_id"),
                "kind": problem.get("kind"),
                "title": problem.get("title"),
                "status": problem.get("status"),
                "severity": problem.get("severity"),
                "march_category": problem.get("march_category"),
                "anatomical_location": problem.get("anatomical_location"),
                "laterality": problem.get("laterality"),
                "cause_kind": problem.get("cause_kind"),
                "cause_id": problem.get("cause_id"),
                "parent_problem_id": problem.get("parent_problem_id"),
                "triggering_intervention_id": problem.get("triggering_intervention_id"),
                "age_seconds": active_problem_ages.get(problem.get("problem_id")),
                "description": _truncate(problem.get("description"), 180) if trim_level < 2 else "",
            }
        )
        for problem in snapshot.get("problems", [])
    ]
    findings = [
        _strip_empty(
            {
                "finding_id": finding.get("finding_id"),
                "kind": finding.get("kind"),
                "title": finding.get("title"),
                "status": finding.get("status"),
                "severity": finding.get("severity"),
                "target_problem_id": finding.get("target_problem_id"),
                "anatomical_location": finding.get("anatomical_location"),
                "laterality": finding.get("laterality"),
                "description": _truncate(finding.get("description"), 140)
                if trim_level == 0
                else "",
            }
        )
        for finding in snapshot.get("assessment_findings", [])
        if _finding_is_relevant(finding, trim_level=trim_level)
    ]
    vitals_summary = _project_vitals_summary(session, snapshot)
    pulses = [
        _strip_empty(
            {
                "location": pulse.get("location"),
                "present": pulse.get("present"),
                "description": pulse.get("description"),
                "color_description": pulse.get("color_description"),
                "condition_description": pulse.get("condition_description"),
                "temperature_description": pulse.get("temperature_description"),
            }
        )
        for pulse in snapshot.get("pulses", [])
        if _pulse_is_relevant(pulse, trim_level=trim_level)
    ]
    interventions = [
        _strip_empty(
            {
                "intervention_id": intervention.get("intervention_id"),
                "kind": intervention.get("kind"),
                "title": intervention.get("title"),
                "site_code": intervention.get("site_code"),
                "target_problem_id": intervention.get("target_problem_id"),
                "initiated_by_type": intervention.get("initiated_by_type"),
                "status": intervention.get("status"),
                "effectiveness": intervention.get("effectiveness"),
                "clinical_effect": _truncate(intervention.get("clinical_effect"), 120),
                "notes": _truncate(intervention.get("notes"), 120) if trim_level < 2 else "",
                "age_seconds": active_intervention_ages.get(intervention.get("intervention_id")),
            }
        )
        for intervention in snapshot.get("interventions", [])
    ]
    patient_status = _project_patient_status(
        snapshot=snapshot,
        active_problems=active_problems,
        vitals_summary=vitals_summary,
    )

    projected = {
        "active_elapsed_seconds": int(active_elapsed_seconds),
        "patient_status": patient_status,
        "active_causes": active_causes,
        "active_problems": active_problems,
        "active_severe_findings": findings,
        "vitals_summary": vitals_summary,
        "pulse_summary": pulses,
        "interventions": interventions,
    }

    if trim_level == 0:
        scenario_context = _project_scenario_context(snapshot.get("scenario_brief") or {})
        if scenario_context:
            projected["scenario_context"] = scenario_context

    if trim_level < 2:
        recommendation_summary = _project_recommendation_summary(snapshot, trim_level=trim_level)
        if recommendation_summary:
            projected["recommendation_summary"] = recommendation_summary

        diagnostic_summary = _project_diagnostic_summary(snapshot, trim_level=trim_level)
        if diagnostic_summary:
            projected["diagnostic_summary"] = diagnostic_summary

    if trim_level == 0:
        resource_summary = _project_resource_summary(session, snapshot)
        if resource_summary:
            projected["resource_summary"] = resource_summary

        disposition_summary = _project_disposition_summary(snapshot.get("disposition"))
        if disposition_summary:
            projected["disposition_summary"] = disposition_summary

    return _strip_empty(projected)


def build_runtime_llm_context(
    session: TrainerSession,
    *,
    current_snapshot: dict[str, Any] | None,
    runtime_reasons: Sequence[dict[str, Any]] | None,
    active_elapsed_seconds: int,
    max_reasons: int | None = None,
    trim_level: int = 0,
) -> dict[str, Any]:
    projected = project_runtime_llm_snapshot(
        session,
        current_snapshot=current_snapshot,
        active_elapsed_seconds=active_elapsed_seconds,
        trim_level=trim_level,
    )
    projected["pending_runtime_reasons"] = compact_runtime_reasons(
        runtime_reasons,
        max_reasons=max_reasons,
        trim_level=trim_level,
    )
    projected["pending_reason_count"] = len(list(runtime_reasons or []))
    if trim_level > 0:
        for field_name in _LOW_PRIORITY_CONTEXT_FIELDS:
            projected.pop(field_name, None)
    return _strip_empty(projected)


def estimate_runtime_request_tokens(
    *,
    service_cls,
    context: dict[str, Any],
    user_message: str,
    request_model: str,
    response_budget_tokens: int,
) -> dict[str, Any]:
    encoding = _encoding_for_model(request_model)
    prompt_sections = _render_service_prompt_sections(service_cls, context)
    if user_message:
        prompt_sections.append(f"USER:{user_message}")
    response_schema = getattr(service_cls, "response_schema", None)
    if response_schema is not None:
        prompt_sections.append(
            "RESPONSE_SCHEMA:"
            + json.dumps(
                response_schema.model_json_schema(),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    estimated_prompt_tokens = len(encoding.encode("\n\n".join(prompt_sections)))
    return {
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "estimated_response_budget_tokens": int(response_budget_tokens),
    }


def enforce_runtime_token_budget(
    *,
    service_cls,
    session: TrainerSession,
    current_snapshot: dict[str, Any] | None,
    runtime_reasons: Sequence[dict[str, Any]] | None,
    active_elapsed_seconds: int,
    user_message: str,
    request_model: str,
    max_prompt_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_reasons: int | None = None,
) -> RuntimeBudgetResult:
    prompt_limit = max_prompt_tokens or get_runtime_max_prompt_tokens()
    output_limit = max_output_tokens or get_runtime_max_output_tokens()
    max_reason_count = max_reasons or get_runtime_max_batch_reasons()
    snapshot_payload = dict(current_snapshot or {})
    raw_reasons = list(runtime_reasons or [])
    snapshot_bytes = json_byte_length(snapshot_payload)
    runtime_reasons_bytes = json_byte_length(raw_reasons)
    attempts = (
        (0, max_reason_count),
        (1, max_reason_count),
        (2, min(max_reason_count, 4)),
        (3, min(max_reason_count, 2)),
    )

    budget_triggered = False
    last_result: RuntimeBudgetResult | None = None

    # The old runtime path bloated prompts with three large inputs: the full current_snapshot,
    # raw runtime reasons, and hidden previous-response carryover. This builder keeps only the
    # compact, authoritative state projection the runtime adjudicator actually needs.
    for trim_level, attempt_max_reasons in attempts:
        runtime_llm_context = build_runtime_llm_context(
            session,
            current_snapshot=snapshot_payload,
            runtime_reasons=raw_reasons,
            active_elapsed_seconds=active_elapsed_seconds,
            max_reasons=attempt_max_reasons,
            trim_level=trim_level,
        )
        compact_reasons = list(runtime_llm_context.get("pending_runtime_reasons") or [])
        request_context = {
            "simulation_id": session.simulation_id,
            "session_id": session.id,
            "active_elapsed_seconds": active_elapsed_seconds,
            "runtime_llm_context": runtime_llm_context,
            "runtime_reasons": compact_reasons,
        }
        estimates = estimate_runtime_request_tokens(
            service_cls=service_cls,
            context=request_context,
            user_message=user_message,
            request_model=request_model,
            response_budget_tokens=output_limit,
        )
        metrics = {
            **estimates,
            "full_snapshot_bytes": snapshot_bytes,
            "runtime_reasons_bytes": runtime_reasons_bytes,
            "runtime_llm_context_bytes": json_byte_length(runtime_llm_context),
            "compacted_runtime_reasons_bytes": json_byte_length(compact_reasons),
            "previous_response_id_present": False,
            "pending_reason_count": len(raw_reasons),
            "compacted_reason_count": len(compact_reasons),
            "request_model": request_model,
            "budget_triggered": budget_triggered,
            "budget_trim_level": trim_level,
            "budget_action": "accepted",
        }
        if estimates["estimated_prompt_tokens"] <= prompt_limit:
            if budget_triggered:
                metrics["budget_action"] = "trimmed"
                metrics["budget_triggered"] = True
            return RuntimeBudgetResult(
                runtime_llm_context=runtime_llm_context,
                runtime_reasons=compact_reasons,
                metrics=metrics,
                allowed=True,
            )

        budget_triggered = True
        metrics["budget_triggered"] = True
        metrics["budget_action"] = "trim_retry"
        last_result = RuntimeBudgetResult(
            runtime_llm_context=runtime_llm_context,
            runtime_reasons=compact_reasons,
            metrics=metrics,
            allowed=False,
        )

    if last_result is None:
        raise RuntimeError("runtime token budget enforcement produced no attempts")

    blocked_metrics = {
        **last_result.metrics,
        "budget_triggered": True,
        "budget_action": "blocked",
        "prompt_budget_exceeded": True,
        "max_prompt_tokens": prompt_limit,
        "max_output_tokens": output_limit,
    }
    return RuntimeBudgetResult(
        runtime_llm_context=last_result.runtime_llm_context,
        runtime_reasons=last_result.runtime_reasons,
        metrics=blocked_metrics,
        allowed=False,
        error_code="prompt_budget_exceeded",
        error_message=(
            "TrainerLab runtime request exceeded the configured prompt budget after compacting "
            "the authoritative state projection."
        ),
    )


def _render_service_prompt_sections(service_cls, context: dict[str, Any]) -> list[str]:
    service = service_cls(context=context)
    sections: list[str] = []
    for instruction_cls in collect_instructions(service_cls):
        has_custom_render = (
            hasattr(instruction_cls, "render_instruction")
            and instruction_cls.render_instruction is not BaseInstruction.render_instruction
        )
        if has_custom_render:
            rendered = instruction_cls.render_instruction(service)
        else:
            rendered = instruction_cls.instruction
        if rendered:
            sections.append(str(rendered))
    return sections


def _encoding_for_model(model_name: str):
    normalized = model_name.split(":", 1)[-1] if ":" in model_name else model_name
    normalized = normalized.strip()
    try:
        return tiktoken.encoding_for_model(normalized)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")


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


def _runtime_reason_dedupe_key(reason: dict[str, Any]) -> tuple[Any, ...]:
    reason_kind = str(reason.get("reason_kind") or "unknown")
    payload = dict(reason.get("payload") or {})
    for field_name in ("domain_event_id", "command_id", "note_id", "preset_id", "injury_event_id"):
        if payload.get(field_name) not in (None, ""):
            return (reason_kind, field_name, payload.get(field_name))
    return (reason_kind, reason.get("created_at"), render_runtime_llm_context(payload))


def _project_patient_status(
    *,
    snapshot: dict[str, Any],
    active_problems: Sequence[dict[str, Any]],
    vitals_summary: dict[str, Any],
) -> dict[str, Any]:
    existing_status = dict(snapshot.get("patient_status") or {})
    active_kinds = {str(problem.get("kind") or "") for problem in active_problems}
    hemodynamic_instability = bool(
        {"hemorrhage", "hypoperfusion_shock"} & active_kinds
        or _vitals_indicate_hemodynamic_instability(vitals_summary)
    )
    respiratory_distress = bool(
        {"respiratory_distress", "hypoxia", "tension_pneumothorax"} & active_kinds
        or _vitals_indicate_respiratory_distress(vitals_summary)
    )
    tension_pneumothorax = "tension_pneumothorax" in active_kinds
    impending_pneumothorax = bool(
        existing_status.get("impending_pneumothorax")
        or ("open_chest_wound" in active_kinds and not tension_pneumothorax)
    )
    return _strip_empty(
        {
            "avpu": existing_status.get("avpu"),
            "respiratory_distress": respiratory_distress,
            "hemodynamic_instability": hemodynamic_instability,
            "impending_pneumothorax": impending_pneumothorax,
            "tension_pneumothorax": tension_pneumothorax,
            "narrative": _build_deterministic_narrative(
                active_kinds=active_kinds,
                vitals_summary=vitals_summary,
            ),
            "teaching_flags": list(existing_status.get("teaching_flags") or []),
        }
    )


def _build_deterministic_narrative(
    *,
    active_kinds: set[str],
    vitals_summary: dict[str, Any],
) -> str:
    if "tension_pneumothorax" in active_kinds:
        return "Critical respiratory compromise with tension physiology is present."
    if {"respiratory_distress", "hypoxia"} & active_kinds:
        return "Respiratory status is unstable and worsening."
    if {"hemorrhage", "hypoperfusion_shock"} & active_kinds:
        return "Hemodynamic status is unstable with ongoing shock risk."
    if _vitals_indicate_respiratory_distress(vitals_summary):
        return "Respiratory parameters remain concerning and need close reassessment."
    if _vitals_indicate_hemodynamic_instability(vitals_summary):
        return "Circulatory parameters remain concerning and need close reassessment."
    if "infectious_process" in active_kinds:
        return "The patient remains clinically ill with an active infectious process."
    return "Patient status is being actively reassessed."


def _project_vitals_summary(
    session: TrainerSession,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    by_type = {
        str(item.get("vital_type")): dict(item)
        for item in snapshot.get("vitals", [])
        if item.get("vital_type")
    }
    summary: dict[str, Any] = {}
    for vital_type, current in by_type.items():
        model = _VITAL_MODEL_MAP.get(vital_type)
        if model is None:
            continue
        value_fields = ["min_value", "max_value"]
        if vital_type == "blood_pressure":
            value_fields.extend(["min_value_diastolic", "max_value_diastolic"])
        previous = list(
            model.objects.filter(simulation=session.simulation)
            .order_by("-timestamp", "-id")
            .values(*value_fields)[:2]
        )
        current_value = previous[0] if previous else {}
        prior_value = previous[1] if len(previous) > 1 else {}
        summary[vital_type] = _strip_empty(
            {
                "current": _project_single_vital(current),
                "trend": _derive_vital_trend(vital_type, current_value, prior_value),
            }
        )
    return summary


def _project_single_vital(current: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "min_value": current.get("min_value"),
        "max_value": current.get("max_value"),
        "lock_value": bool(current.get("lock_value", False)),
    }
    if current.get("vital_type") == "blood_pressure":
        projected["min_value_diastolic"] = current.get("min_value_diastolic")
        projected["max_value_diastolic"] = current.get("max_value_diastolic")
    return _strip_empty(projected)


def _derive_vital_trend(
    vital_type: str,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> str:
    if not current or not previous:
        return "stable"

    current_midpoint = _vital_midpoint(vital_type, current)
    previous_midpoint = _vital_midpoint(vital_type, previous)
    if current_midpoint is None or previous_midpoint is None:
        return "stable"
    if abs(current_midpoint - previous_midpoint) < 0.5:
        return "stable"
    return "up" if current_midpoint > previous_midpoint else "down"


def _vital_midpoint(vital_type: str, value: dict[str, Any]) -> float | None:
    if vital_type == "blood_pressure":
        systolic = _average(value.get("min_value"), value.get("max_value"))
        diastolic = _average(
            value.get("min_value_diastolic"),
            value.get("max_value_diastolic"),
        )
        if systolic is None or diastolic is None:
            return None
        return systolic + diastolic / 1000.0
    return _average(value.get("min_value"), value.get("max_value"))


def _project_recommendation_summary(
    snapshot: dict[str, Any],
    *,
    trim_level: int,
) -> list[dict[str, Any]]:
    recommendations = sorted(
        snapshot.get("recommended_interventions", []),
        key=lambda item: (
            item.get("priority") is None,
            item.get("priority") if item.get("priority") is not None else 999,
            item.get("recommendation_id") or 0,
        ),
    )
    limit = 6 if trim_level == 0 else 4
    return [
        _strip_empty(
            {
                "recommendation_id": recommendation.get("recommendation_id"),
                "kind": recommendation.get("kind"),
                "title": recommendation.get("title"),
                "target_problem_id": recommendation.get("target_problem_id"),
                "priority": recommendation.get("priority"),
                "site_code": recommendation.get("site_code"),
                "rationale": _truncate(recommendation.get("rationale"), 120)
                if trim_level == 0
                else "",
            }
        )
        for recommendation in recommendations[:limit]
    ]


def _project_diagnostic_summary(
    snapshot: dict[str, Any],
    *,
    trim_level: int,
) -> list[dict[str, Any]]:
    items = [
        _strip_empty(
            {
                "diagnostic_id": diagnostic.get("diagnostic_id"),
                "kind": diagnostic.get("kind"),
                "title": diagnostic.get("title"),
                "status": diagnostic.get("status"),
                "value_text": _truncate(diagnostic.get("value_text"), 120),
                "target_problem_id": diagnostic.get("target_problem_id"),
            }
        )
        for diagnostic in snapshot.get("diagnostic_results", [])
        if diagnostic.get("status") not in {"normal", "resolved"}
        or diagnostic.get("value_text")
        or diagnostic.get("target_problem_id")
    ]
    return items[: max(3, 6 - trim_level)]


def _project_resource_summary(
    session: TrainerSession,
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    constrained_codes = {
        code
        for code, status, quantity in ResourceState.objects.filter(
            simulation=session.simulation,
            is_active=True,
        ).values_list("code", "status", "quantity_available")
        if status in {ResourceState.Status.UNAVAILABLE, ResourceState.Status.LIMITED}
        or quantity <= 1
    }
    items = []
    for resource in snapshot.get("resources", []):
        code = resource.get("code")
        if code not in constrained_codes:
            continue
        items.append(
            _strip_empty(
                {
                    "resource_id": resource.get("resource_id"),
                    "kind": resource.get("kind"),
                    "title": resource.get("title"),
                    "status": resource.get("status"),
                    "quantity_available": resource.get("quantity_available"),
                    "quantity_unit": resource.get("quantity_unit"),
                }
            )
        )
    return items[:6]


def _project_disposition_summary(disposition: dict[str, Any] | None) -> dict[str, Any]:
    if not disposition:
        return {}
    if not any(
        disposition.get(field)
        for field in (
            "transport_mode",
            "destination",
            "eta_minutes",
            "handoff_ready",
            "scene_constraints",
        )
    ) and disposition.get("status") in {"", "hold", None}:
        return {}
    return _strip_empty(
        {
            "status": disposition.get("status"),
            "transport_mode": disposition.get("transport_mode"),
            "destination": disposition.get("destination"),
            "eta_minutes": disposition.get("eta_minutes"),
            "handoff_ready": disposition.get("handoff_ready"),
            "scene_constraints": disposition.get("scene_constraints"),
        }
    )


def _project_scenario_context(brief: dict[str, Any]) -> dict[str, Any]:
    return _strip_empty(
        {
            "environment": _truncate(brief.get("environment"), 120),
            "location_overview": _truncate(brief.get("location_overview"), 120),
            "threat_context": _truncate(brief.get("threat_context"), 120),
            "evacuation_time": brief.get("evacuation_time"),
            "special_considerations": list(brief.get("special_considerations") or []),
        }
    )


def _finding_is_relevant(finding: dict[str, Any], *, trim_level: int) -> bool:
    severity = str(finding.get("severity") or "")
    status = str(finding.get("status") or "")
    if severity in {"high", "critical"} or status in {"worsening", "present"}:
        return True
    return trim_level == 0 and bool(finding.get("title") or finding.get("description"))


def _pulse_is_relevant(pulse: dict[str, Any], *, trim_level: int) -> bool:
    if not bool(pulse.get("present", True)):
        return True
    if pulse.get("description") in {"weak", "absent", "thready"}:
        return True
    if pulse.get("color_description") not in {"pink", "", None}:
        return True
    if pulse.get("condition_description") not in {"dry", "", None}:
        return True
    if pulse.get("temperature_description") not in {"warm", "", None}:
        return True
    return trim_level == 0


def _vitals_indicate_hemodynamic_instability(vitals_summary: dict[str, Any]) -> bool:
    heart_rate = vitals_summary.get("heart_rate", {}).get("current", {})
    blood_pressure = vitals_summary.get("blood_pressure", {}).get("current", {})
    max_hr = heart_rate.get("max_value")
    min_sbp = blood_pressure.get("min_value")
    return bool(
        (isinstance(max_hr, int) and max_hr >= 120) or (isinstance(min_sbp, int) and min_sbp <= 90)
    )


def _vitals_indicate_respiratory_distress(vitals_summary: dict[str, Any]) -> bool:
    spo2 = vitals_summary.get("spo2", {}).get("current", {})
    respiratory_rate = vitals_summary.get("respiratory_rate", {}).get("current", {})
    min_spo2 = spo2.get("min_value")
    max_rr = respiratory_rate.get("max_value")
    return bool(
        (isinstance(min_spo2, int) and min_spo2 < 92) or (isinstance(max_rr, int) and max_rr >= 28)
    )


def _average(first: Any, second: Any) -> float | None:
    if not isinstance(first, (int, float)) or not isinstance(second, (int, float)):
        return None
    return (float(first) + float(second)) / 2.0


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {
            key: _strip_empty(item) for key, item in value.items() if item not in (None, "", [], {})
        }
        return {key: item for key, item in cleaned.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        cleaned_items = [_strip_empty(item) for item in value]
        return [item for item in cleaned_items if item not in (None, "", [], {})]
    return value


__all__ = [
    "RuntimeBudgetResult",
    "build_runtime_llm_context",
    "compact_runtime_reasons",
    "enforce_runtime_token_budget",
    "estimate_runtime_request_tokens",
    "get_runtime_max_batch_reasons",
    "get_runtime_max_output_tokens",
    "get_runtime_max_prompt_tokens",
    "json_byte_length",
    "project_runtime_llm_snapshot",
    "render_runtime_llm_context",
]
