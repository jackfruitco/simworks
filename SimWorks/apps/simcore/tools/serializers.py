from collections import defaultdict
from typing import Any


def serialize_patient_demographics(item) -> dict[str, Any]:
    return {
        "kind": "patient_demographics",
        "key": item.key,
        "value": item.value,
        "db_pk": item.pk,
    }


def serialize_patient_history(item) -> dict[str, Any]:
    return {
        "kind": "patient_history",
        "key": item.key,
        "value": item.value,
        "db_pk": item.pk,
        "diagnosis": item.diagnosis,
        "is_resolved": item.is_resolved,
        "duration": item.duration,
        "summary": (
            f"History of {item.diagnosis} "
            f"({'now resolved' if item.is_resolved else 'ongoing'}, for {item.duration})"
        ),
    }


def serialize_lab_result(item) -> dict[str, Any]:
    return {
        "kind": "lab_result",
        "db_pk": item.pk,
        "key": item.key,
        "result_name": item.key,
        "panel_name": item.panel_name or None,
        "value": item.value,
        "unit": item.result_unit,
        "reference_range_high": item.reference_range_high,
        "reference_range_low": item.reference_range_low,
        "flag": item.result_flag,
        "attribute": item.attribute,
        "type": item.attribute,
    }


def _coerce_criterion_score_value(score) -> Any:
    """Surface the typed value for a single AssessmentCriterionScore row."""
    criterion = score.criterion
    vt = criterion.value_type
    if vt == "bool":
        return score.value_bool
    if vt == "int":
        return score.value_int
    if vt == "decimal":
        return float(score.value_decimal) if score.value_decimal is not None else None
    if vt in {"text", "enum"}:
        return score.value_text or None
    if vt == "json":
        return score.value_json
    return None


def _serialize_criterion_score(score) -> dict[str, Any]:
    return {
        "slug": score.criterion.slug,
        "label": score.criterion.label,
        "value": _coerce_criterion_score_value(score),
        "score": float(score.score) if score.score is not None else None,
        "rationale": score.rationale,
        "evidence": score.evidence or [],
    }


def serialize_assessment(assessment) -> dict[str, Any]:
    """Render an Assessment in the simulation-tools API shape.

    Returns a single tool-data item (``kind="simulation_assessment"``)
    with the criterion scores grouped by category. Categories preserve
    their YAML-defined order via ``criterion.sort_order``.
    """
    scores = list(
        assessment.criterion_scores.select_related("criterion").order_by("criterion__sort_order")
    )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    category_order: list[str] = []
    for score in scores:
        category = score.criterion.category or ""
        if category not in groups:
            category_order.append(category)
        groups[category].append(_serialize_criterion_score(score))

    return {
        "kind": "simulation_assessment",
        "db_pk": None,
        "assessment_id": str(assessment.id),
        "assessment_type": assessment.assessment_type,
        "lab_type": assessment.lab_type,
        "rubric": {
            "slug": assessment.rubric.slug,
            "version": assessment.rubric.version,
            "name": assessment.rubric.name,
        },
        "overall_summary": assessment.overall_summary,
        "overall_score": (
            float(assessment.overall_score) if assessment.overall_score is not None else None
        ),
        "groups": [
            {"category": category, "criteria": groups[category]} for category in category_order
        ],
    }
