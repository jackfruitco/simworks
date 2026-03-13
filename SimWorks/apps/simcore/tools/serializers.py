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


def serialize_simulation_feedback(item) -> dict[str, Any]:
    value: bool | int | str = item.value
    if item.key in {"hotwash_correct_diagnosis", "hotwash_correct_treatment_plan"}:
        value = item.value == "True"
    elif item.key == "hotwash_patient_experience":
        value = int(item.value)

    return {
        "kind": "simulation_feedback",
        "key": item.key,
        "value": value,
        "db_pk": item.pk,
    }
