import pytest

from apps.trainerlab.injury_dictionary import (
    get_injury_dictionary_choices,
    get_injury_mapping_warnings,
    normalize_injury_category,
    normalize_injury_kind,
    normalize_injury_location,
)
from apps.trainerlab.models import Injury, Problem


def test_dictionary_choices_match_orm_choices():
    choices = get_injury_dictionary_choices()

    assert choices["categories"] == [
        (str(code), str(label)) for code, label in Problem.MARCHCategory.choices
    ]
    assert choices["regions"] == [
        (str(code), str(label)) for code, label in Injury.InjuryLocation.choices
    ]
    assert choices["kinds"] == [
        (str(code), str(label)) for code, label in Injury.InjuryKind.choices
    ]


def test_normalizes_codes_and_friendly_labels():
    assert normalize_injury_category("m") == "M"
    assert normalize_injury_category(" Massive   Hemorrhage ") == "M"
    assert normalize_injury_location("hla") == "HLA"
    assert normalize_injury_location("left anterior head") == "HLA"
    assert normalize_injury_kind("laceration") == "LAC"
    assert normalize_injury_kind(" LAC ") == "LAC"


def test_rejects_unknown_values_with_explicit_error():
    with pytest.raises(ValueError, match="Invalid 'injury_location' value"):
        normalize_injury_location("not-a-real-location")


def test_integrity_guard_surfaces_pfc_pc_mismatch_warning():
    warnings = get_injury_mapping_warnings()
    assert any("PFC" in warning and "PC" in warning for warning in warnings)
