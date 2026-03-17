from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slugify import slugify

from .intervention_dictionary import (
    get_intervention_label,
    get_intervention_site_label,
    normalize_intervention_site,
    normalize_intervention_type,
    normalize_site_code,
)
from .models import Problem, RecommendedIntervention

_PROBLEM_INTERVENTION_COMPATIBILITY: dict[str, frozenset[str]] = {
    "hemorrhage": frozenset(
        {
            "tourniquet",
            "junctional_tourniquet",
            "pressure_dressing",
            "wound_packing",
            "hemostatic_agent",
        }
    ),
    "open_wound": frozenset({"pressure_dressing", "wound_packing", "hemostatic_agent"}),
    "open_chest_wound": frozenset({"chest_seal"}),
    "airway_obstruction": frozenset({"npa", "opa", "advanced_airway", "surgical_cric"}),
    "tension_pneumothorax": frozenset({"needle_decompression", "chest_tube"}),
    "infectious_process": frozenset({"antibiotics"}),
}


def _normalized_text(value: str) -> str:
    return " ".join(value.strip().split())


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value)]


@dataclass(frozen=True)
class RecommendationNormalizationResult:
    accepted: bool
    recommendation_source: str
    validation_status: str
    kind: str = ""
    code: str = ""
    slug: str = ""
    title: str = ""
    display_name: str = ""
    site_code: str = ""
    site_label: str = ""
    rationale: str = ""
    priority: int | None = None
    warnings: list[str] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def is_recommendation_compatible(*, problem_kind: str, intervention_kind: str) -> bool:
    allowed = _PROBLEM_INTERVENTION_COMPATIBILITY.get(problem_kind)
    if allowed is None:
        return True
    return intervention_kind in allowed


def validate_and_normalize_recommendation(
    *,
    problem: Problem,
    raw_kind: str,
    raw_title: str = "",
    raw_site: str = "",
    rationale: str = "",
    priority: int | None = None,
    warnings: list[str] | None = None,
    contraindications: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RecommendationNormalizationResult:
    initial_metadata = dict(metadata or {})
    raw_value = raw_kind or raw_title
    if not _normalized_text(raw_value):
        return RecommendationNormalizationResult(
            accepted=False,
            recommendation_source=RecommendedIntervention.RecommendationSource.MERGED,
            validation_status=RecommendedIntervention.ValidationStatus.REJECTED,
            metadata={**initial_metadata, "rejection_reason": "missing_intervention_kind"},
        )

    try:
        normalized_kind = normalize_intervention_type(raw_value)
    except ValueError as exc:
        return RecommendationNormalizationResult(
            accepted=False,
            recommendation_source=RecommendedIntervention.RecommendationSource.MERGED,
            validation_status=RecommendedIntervention.ValidationStatus.REJECTED,
            metadata={**initial_metadata, "rejection_reason": str(exc)},
        )

    if not is_recommendation_compatible(
        problem_kind=problem.kind, intervention_kind=normalized_kind
    ):
        return RecommendationNormalizationResult(
            accepted=False,
            recommendation_source=RecommendedIntervention.RecommendationSource.MERGED,
            validation_status=RecommendedIntervention.ValidationStatus.REJECTED,
            metadata={
                **initial_metadata,
                "rejection_reason": (
                    f"{normalized_kind!r} is not a valid recommendation for {problem.kind!r}"
                ),
            },
        )

    validation_status = RecommendedIntervention.ValidationStatus.ACCEPTED
    recommendation_source = RecommendedIntervention.RecommendationSource.AI

    site_code = ""
    site_label = ""
    normalization_warnings = list(warnings or [])
    if _normalized_text(raw_site):
        try:
            site_code = normalize_site_code(normalize_intervention_site(normalized_kind, raw_site))
            site_label = get_intervention_site_label(normalized_kind, site_code)
        except ValueError as exc:
            validation_status = RecommendedIntervention.ValidationStatus.DOWNGRADED
            recommendation_source = RecommendedIntervention.RecommendationSource.MERGED
            normalization_warnings.append(str(exc))

    if _normalized_text(raw_value) != normalized_kind:
        validation_status = RecommendedIntervention.ValidationStatus.NORMALIZED
        recommendation_source = RecommendedIntervention.RecommendationSource.MERGED

    title = get_intervention_label(normalized_kind)
    display_name = raw_title or title
    code = normalized_kind
    slug = slugify(normalized_kind, separator="_")

    return RecommendationNormalizationResult(
        accepted=True,
        recommendation_source=recommendation_source,
        validation_status=validation_status,
        kind=normalized_kind,
        code=code,
        slug=slug,
        title=title,
        display_name=display_name,
        site_code=site_code,
        site_label=site_label,
        rationale=rationale,
        priority=priority,
        warnings=normalization_warnings,
        contraindications=_as_list(contraindications),
        metadata=initial_metadata,
    )
