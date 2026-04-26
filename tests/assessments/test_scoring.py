"""Unit tests for scoring helpers (no DB required for the pure ones)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

# Lightweight criterion stub for pure-function tests. The scoring
# helpers only access ``value_type``, ``min_value``, ``max_value`` and
# (for compute_overall_score) ``criterion.weight`` + ``score``.


def _criterion_stub(value_type, *, min_value=None, max_value=None, weight=1):
    return SimpleNamespace(
        value_type=value_type,
        min_value=min_value,
        max_value=max_value,
        weight=Decimal(weight),
    )


def _score_stub(criterion, score):
    return SimpleNamespace(criterion=criterion, score=score)


def test_normalize_bool_true_returns_one():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("bool")
    assert normalize_criterion_value(c, value_bool=True) == Decimal("1")


def test_normalize_bool_false_returns_zero():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("bool")
    assert normalize_criterion_value(c, value_bool=False) == Decimal("0")


def test_normalize_bool_none_returns_none():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("bool")
    assert normalize_criterion_value(c, value_bool=None) is None


def test_normalize_int_with_bounds():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("int", min_value=Decimal("0"), max_value=Decimal("5"))
    assert normalize_criterion_value(c, value_int=4) == Decimal("0.800")


def test_normalize_int_clamped_below_min():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("int", min_value=Decimal("0"), max_value=Decimal("5"))
    assert normalize_criterion_value(c, value_int=-1) == Decimal("0")


def test_normalize_int_clamped_above_max():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("int", min_value=Decimal("0"), max_value=Decimal("5"))
    assert normalize_criterion_value(c, value_int=99) == Decimal("1")


def test_normalize_int_without_bounds_returns_none():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("int")
    assert normalize_criterion_value(c, value_int=4) is None


def test_normalize_decimal_with_bounds():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("decimal", min_value=Decimal("0"), max_value=Decimal("10"))
    assert normalize_criterion_value(c, value_decimal=Decimal("2.5")) == Decimal("0.250")


def test_normalize_min_equals_max_returns_zero():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("int", min_value=Decimal("3"), max_value=Decimal("3"))
    assert normalize_criterion_value(c, value_int=3) == Decimal("0")


def test_normalize_text_returns_none():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("text")
    assert normalize_criterion_value(c, value_text="hello") is None


def test_normalize_enum_returns_none():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("enum")
    assert normalize_criterion_value(c, value_text="medium") is None


def test_normalize_json_returns_none():
    from apps.assessments.services import normalize_criterion_value

    c = _criterion_stub("json")
    assert normalize_criterion_value(c, value_json={"a": 1}) is None


def test_compute_overall_weighted_mean_equal_weights():
    from apps.assessments.services import compute_overall_score

    scores = [
        _score_stub(_criterion_stub("bool"), Decimal("1.000")),
        _score_stub(_criterion_stub("bool"), Decimal("0.000")),
        _score_stub(_criterion_stub("int"), Decimal("0.800")),
    ]
    # (1.0 + 0.0 + 0.8) / 3 = 0.600
    assert compute_overall_score(scores) == Decimal("0.600")


def test_compute_overall_weighted_mean_unequal_weights():
    from apps.assessments.services import compute_overall_score

    scores = [
        _score_stub(_criterion_stub("bool", weight=2), Decimal("1.000")),
        _score_stub(_criterion_stub("bool", weight=1), Decimal("0.000")),
        _score_stub(_criterion_stub("int", weight=1), Decimal("0.800")),
    ]
    # (2*1 + 1*0 + 1*0.8) / 4 = 0.700
    assert compute_overall_score(scores) == Decimal("0.700")


def test_compute_overall_skips_none_scores():
    from apps.assessments.services import compute_overall_score

    scores = [
        _score_stub(_criterion_stub("bool"), Decimal("1.000")),
        _score_stub(_criterion_stub("text"), None),
        _score_stub(_criterion_stub("bool"), Decimal("0.000")),
    ]
    assert compute_overall_score(scores) == Decimal("0.500")


def test_compute_overall_returns_none_when_all_none():
    from apps.assessments.services import compute_overall_score

    scores = [
        _score_stub(_criterion_stub("text"), None),
        _score_stub(_criterion_stub("enum"), None),
    ]
    assert compute_overall_score(scores) is None


def test_compute_overall_zero_weights_excluded():
    from apps.assessments.services import compute_overall_score

    scores = [
        _score_stub(_criterion_stub("bool", weight=0), Decimal("1.000")),
        _score_stub(_criterion_stub("bool", weight=2), Decimal("0.500")),
    ]
    # Only the second score counts → 0.500.
    assert compute_overall_score(scores) == Decimal("0.500")
