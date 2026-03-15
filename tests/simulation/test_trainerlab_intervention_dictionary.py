import pytest

from apps.trainerlab.intervention_dictionary import (
    build_legacy_intervention_code,
    get_intervention_definition,
    get_intervention_detail_schema_metadata,
    get_intervention_site_label,
    get_intervention_type_choices,
    normalize_intervention_site,
    normalize_intervention_type,
    validate_intervention_details,
)


def test_registry_exposes_typed_frontend_metadata():
    assert ("tourniquet", "Tourniquet") in get_intervention_type_choices()
    assert get_intervention_detail_schema_metadata("tourniquet") == {
        "kind": "tourniquet",
        "version": 1,
        "required_fields": ["application_mode"],
        "optional_fields": [],
        "allows_extra": False,
    }
    definition = get_intervention_definition("needle_decompression")
    assert definition.ui_fields == ()


def test_normalizes_codes_labels_and_validates_details():
    assert normalize_intervention_type("Tourniquet") == "tourniquet"
    assert normalize_intervention_site("tourniquet", "left arm") == "LEFT_ARM"
    assert get_intervention_site_label("tourniquet", "LEFT_ARM") == "Left Arm"
    assert validate_intervention_details(
        "tourniquet",
        {"kind": "tourniquet", "version": 1, "application_mode": " Deliberate "},
    ) == {
        "kind": "tourniquet",
        "version": 1,
        "application_mode": "deliberate",
    }
    assert validate_intervention_details(
        "needle_decompression",
        {"kind": "needle_decompression", "version": 1},
    ) == {
        "kind": "needle_decompression",
        "version": 1,
    }


def test_rejects_invalid_sites_and_detail_payloads():
    with pytest.raises(ValueError, match=r"Invalid 'tourniquet\.site_code' value"):
        normalize_intervention_site("tourniquet", "not-a-real-site")

    with pytest.raises(ValueError, match="application_mode"):
        validate_intervention_details("tourniquet", {"kind": "tourniquet", "version": 1})

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_intervention_details(
            "needle_decompression",
            {
                "kind": "needle_decompression",
                "version": 1,
                "air_return_observed": True,
            },
        )

    assert (
        build_legacy_intervention_code(
            "tourniquet",
            {"kind": "tourniquet", "version": 1, "application_mode": "hasty"},
        )
        == "M-TQ-H"
    )
