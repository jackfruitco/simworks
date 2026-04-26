"""Scoring helpers: typed-value → normalized 0..1 score, weighted overall.

These helpers are pure functions so they can be unit tested without a DB.
The persistence service in Phase 3 calls them while writing
:class:`AssessmentCriterionScore` rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from apps.assessments.models import AssessmentCriterion, AssessmentCriterionScore


def normalize_criterion_value(
    criterion: AssessmentCriterion,
    *,
    value_bool: bool | None = None,
    value_int: int | None = None,
    value_decimal: Decimal | None = None,
    value_text: str = "",
    value_json=None,
) -> Decimal | None:
    """Map a typed criterion value onto a normalized 0..1 score.

    - ``bool``: ``True`` → 1, ``False`` → 0, ``None`` → ``None``.
    - ``int`` / ``decimal`` with both ``min_value`` and ``max_value``
      defined: clamped linear normalization. Returns 0 when min == max.
    - ``int`` / ``decimal`` without bounds, ``enum``, ``text``, ``json``:
      returns ``None`` (caller may attach a manually authored score).
    """
    vt = criterion.value_type

    if vt == AssessmentCriterion.ValueType.BOOL:
        if value_bool is None:
            return None
        return Decimal("1") if value_bool else Decimal("0")

    if vt in {
        AssessmentCriterion.ValueType.INT,
        AssessmentCriterion.ValueType.DECIMAL,
    }:
        raw = value_int if vt == AssessmentCriterion.ValueType.INT else value_decimal
        if raw is None or criterion.min_value is None or criterion.max_value is None:
            return None
        lo = Decimal(criterion.min_value)
        hi = Decimal(criterion.max_value)
        v = Decimal(raw)
        if hi == lo:
            return Decimal("0")
        normalized = (v - lo) / (hi - lo)
        if normalized < 0:
            return Decimal("0")
        if normalized > 1:
            return Decimal("1")
        return normalized.quantize(Decimal("0.001"))

    return None


def compute_overall_score(
    criterion_scores: Iterable[AssessmentCriterionScore],
) -> Decimal | None:
    """Weighted mean of non-null criterion scores, weighted by criterion.weight.

    Returns ``None`` if every score is ``None`` or every weight is zero.
    """
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for cs in criterion_scores:
        if cs.score is None:
            continue
        weight = Decimal(cs.criterion.weight)
        if weight <= 0:
            continue
        total_weight += weight
        weighted_sum += weight * cs.score
    if total_weight == 0:
        return None
    return (weighted_sum / total_weight).quantize(Decimal("0.001"))
