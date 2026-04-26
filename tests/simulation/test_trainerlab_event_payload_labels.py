from types import SimpleNamespace

from apps.trainerlab.event_payloads import (
    enrich_trainer_payload,
    serialize_assessment_finding_summary,
    serialize_cause_snapshot,
    serialize_problem_snapshot,
)
from apps.trainerlab.injury_dictionary import get_injury_location_label


def test_get_injury_location_label_resolves_canonical_codes_and_labels():
    assert get_injury_location_label("LLL") == "Left Lower Leg"
    assert get_injury_location_label("Lll") == "Left Lower Leg"
    assert get_injury_location_label("Left Lower Leg") == "Left Lower Leg"
    assert get_injury_location_label("left lower leg") == "Left Lower Leg"


def test_enrich_trainer_payload_adds_anatomy_and_laterality_labels_from_code():
    payload = enrich_trainer_payload(
        {
            "anatomical_location": "LLL",
            "laterality": "left",
        }
    )

    assert payload["anatomical_location"] == "LLL"
    assert payload["anatomical_location_label"] == "Left Lower Leg"
    assert payload["laterality"] == "left"
    assert payload["laterality_label"] == "Left"


def test_enrich_trainer_payload_adds_anatomy_labels_from_mixed_case_code():
    payload = enrich_trainer_payload({"anatomical_location": "Lll"})

    assert payload["anatomical_location"] == "Lll"
    assert payload["anatomical_location_label"] == "Left Lower Leg"


def test_enrich_trainer_payload_adds_anatomy_labels_from_canonical_label():
    payload = enrich_trainer_payload({"anatomical_location": "Left Lower Leg"})

    assert payload["anatomical_location"] == "Left Lower Leg"
    assert payload["anatomical_location_label"] == "Left Lower Leg"


def test_enrich_trainer_payload_adds_anatomy_labels_from_lowercase_label():
    payload = enrich_trainer_payload({"anatomical_location": "left lower leg"})

    assert payload["anatomical_location"] == "left lower leg"
    assert payload["anatomical_location_label"] == "Left Lower Leg"


def test_enrich_trainer_payload_humanizes_unknown_anatomy_values():
    payload = enrich_trainer_payload(
        {
            "anatomical_location": "left-lower-calf",
            "laterality": "patientRight",
        }
    )

    assert payload["anatomical_location"] == "left-lower-calf"
    assert payload["anatomical_location_label"] == "Left Lower Calf"
    assert payload["laterality_label"] == "Patient Right"


def test_enrich_trainer_payload_uses_empty_labels_for_empty_raw_values():
    payload = enrich_trainer_payload(
        {
            "anatomical_location": "",
            "laterality": None,
        }
    )

    assert payload["anatomical_location_label"] == ""
    assert payload["laterality_label"] == ""


def test_problem_snapshot_includes_anatomy_and_laterality_labels():
    problem = SimpleNamespace(
        id=101,
        is_active=True,
        kind="hemorrhage",
        code="HEMORRHAGE",
        slug="hemorrhage",
        title="Hemorrhage",
        display_name="Hemorrhage",
        description="Active bleeding",
        severity="critical",
        march_category="M",
        anatomical_location="LLL",
        laterality="left",
        status="active",
        previous_status="",
        treated_at=None,
        controlled_at=None,
        resolved_at=None,
        cause_id=12,
        cause_kind="injury",
        parent_problem_id=None,
        triggering_intervention_id=None,
        adjudication_reason="",
        adjudication_rule_id="",
        metadata_json={},
        source="system",
        timestamp=None,
    )

    payload = serialize_problem_snapshot(problem)

    assert payload["anatomical_location"] == "LLL"
    assert payload["anatomical_location_label"] == "Left Lower Leg"
    assert payload["laterality"] == "left"
    assert payload["laterality_label"] == "Left"


def test_cause_and_finding_summaries_include_anatomy_labels():
    cause = SimpleNamespace(
        id=201,
        is_active=True,
        cause_kind="injury",
        kind="laceration",
        code="LAC",
        slug="laceration",
        title="Laceration",
        display_name="Laceration",
        description="Leg laceration",
        anatomical_location="LLL",
        laterality="left",
        metadata_json={},
        source="system",
        timestamp=None,
        injury_location="LLL",
        injury_kind="LAC",
    )
    finding = SimpleNamespace(
        id=301,
        is_active=True,
        kind="bleeding",
        code="BLEEDING",
        slug="bleeding",
        title="Bleeding",
        display_name="Bleeding",
        description="Bleeding from wound",
        status="present",
        severity="critical",
        target_problem_id=101,
        anatomical_location="LLL",
        laterality="left",
        metadata_json={},
        source="system",
        timestamp=None,
    )

    cause_payload = serialize_cause_snapshot(cause)
    finding_payload = serialize_assessment_finding_summary(finding)

    assert cause_payload["anatomical_location_label"] == "Left Lower Leg"
    assert cause_payload["laterality_label"] == "Left"
    assert finding_payload["anatomical_location_label"] == "Left Lower Leg"
    assert finding_payload["laterality_label"] == "Left"
