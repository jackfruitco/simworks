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
    "respiratory_distress": frozenset({"chest_seal", "needle_decompression", "advanced_airway"}),
    "tension_pneumothorax": frozenset({"needle_decompression", "chest_tube"}),
    "infectious_process": frozenset({"antibiotics"}),
    "hypoperfusion_shock": frozenset(
        {"iv_access", "io_access", "fluid_resuscitation", "blood_transfusion"}
    ),
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


@dataclass(frozen=True)
class RuleRecommendationSeed:
    problem_id: int
    intervention_kind: str
    title: str
    rationale: str
    priority: int | None = None
    raw_site: str = ""
    warnings: list[str] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def is_recommendation_compatible(*, problem_kind: str, intervention_kind: str) -> bool:
    allowed = _PROBLEM_INTERVENTION_COMPATIBILITY.get(problem_kind)
    if allowed is None:
        return True
    return intervention_kind in allowed


def build_recommendation_compatibility_instruction() -> str:
    lines = [
        "### Recommendation Compatibility",
        "- Recommendations must use only the allowed intervention kinds for each problem kind.",
    ]
    for problem_kind, intervention_kinds in _PROBLEM_INTERVENTION_COMPATIBILITY.items():
        allowed = ", ".join(
            f"`{kind}` ({get_intervention_label(kind)})" for kind in sorted(intervention_kinds)
        )
        lines.append(f"- `{problem_kind}`: {allowed}")
    return "\n".join(lines) + "\n"


def _problem_tokens(problem: Problem) -> set[str]:
    values = [
        problem.anatomical_location,
        problem.laterality,
        problem.title,
        problem.display_name,
    ]
    cause = problem.cause
    if cause is not None:
        values.extend(
            [
                getattr(cause, "anatomical_location", ""),
                getattr(cause, "laterality", ""),
                getattr(cause, "title", ""),
                getattr(cause, "description", ""),
            ]
        )
    tokens: set[str] = set()
    for value in values:
        tokens.update(slugify(value or "", separator="_").split("_"))
    return {token for token in tokens if token}


def _default_site_for_problem(*, problem: Problem, intervention_kind: str) -> str:
    tokens = _problem_tokens(problem)
    laterality = "left" if "left" in tokens else ("right" if "right" in tokens else "")

    if intervention_kind in {"tourniquet", "pressure_dressing"}:
        if {"leg", "thigh", "lower"} & tokens:
            return f"{laterality.upper()}_LEG" if laterality else ""
        if {"arm", "upper", "hand"} & tokens:
            return f"{laterality.upper()}_ARM" if laterality else ""
    if intervention_kind == "chest_seal":
        if "posterior" in tokens:
            return f"{laterality.upper()}_POSTERIOR_CHEST" if laterality else ""
        return f"{laterality.upper()}_ANTERIOR_CHEST" if laterality else ""
    if intervention_kind == "needle_decompression":
        if "lateral" in tokens:
            return f"{laterality.upper()}_LATERAL_CHEST" if laterality else ""
        return f"{laterality.upper()}_ANTERIOR_CHEST" if laterality else ""
    if intervention_kind == "npa":
        return "RIGHT_NARE"
    if intervention_kind == "opa":
        return "ORAL"
    return ""


def generate_rule_based_recommendations(problem: Problem) -> list[RuleRecommendationSeed]:
    if problem.status == Problem.Status.RESOLVED:
        return []

    defaults: dict[str, list[tuple[str, str, int | None]]] = {
        "hemorrhage": [
            ("tourniquet", "Control extremity hemorrhage.", 1),
            (
                "pressure_dressing",
                "Control persistent bleeding if a tourniquet is not applicable.",
                2,
            ),
        ],
        "open_wound": [("pressure_dressing", "Protect and dress the wound.", 2)],
        "open_chest_wound": [("chest_seal", "Seal the chest wound to improve ventilation.", 1)],
        "airway_obstruction": [
            ("npa", "Support airway patency.", 1),
            ("opa", "Support airway patency if appropriate.", 2),
        ],
        "tension_pneumothorax": [
            ("needle_decompression", "Relieve worsening tension physiology.", 1)
        ],
        "infectious_process": [("antibiotics", "Treat the infectious source.", 1)],
        "hypoperfusion_shock": [
            ("fluid_resuscitation", "Support perfusion while definitive treatment continues.", 2)
        ],
        "respiratory_distress": [
            ("chest_seal", "Treat an open chest source if present.", 2),
            ("needle_decompression", "Prepare decompression if tension physiology develops.", 3),
        ],
    }
    items = defaults.get(problem.kind, [])
    return [
        RuleRecommendationSeed(
            problem_id=problem.id,
            intervention_kind=kind,
            title=get_intervention_label(kind),
            rationale=rationale,
            priority=priority,
            raw_site=_default_site_for_problem(problem=problem, intervention_kind=kind),
            metadata={"generated_by": "rules"},
        )
        for kind, rationale, priority in items
        if is_recommendation_compatible(problem_kind=problem.kind, intervention_kind=kind)
    ]


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
    contraindicated_interventions: set[str] | None = None,
    unavailable_interventions: set[str] | None = None,
    limited_interventions: set[str] | None = None,
    source_override: str | None = None,
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
    recommendation_source = source_override or RecommendedIntervention.RecommendationSource.AI

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

    if normalized_kind in (contraindicated_interventions or set()):
        return RecommendationNormalizationResult(
            accepted=False,
            recommendation_source=RecommendedIntervention.RecommendationSource.MERGED,
            validation_status=RecommendedIntervention.ValidationStatus.REJECTED,
            metadata={
                **initial_metadata,
                "rejection_reason": f"{normalized_kind!r} is contraindicated in the current state",
            },
        )

    if normalized_kind in (unavailable_interventions or set()):
        return RecommendationNormalizationResult(
            accepted=False,
            recommendation_source=RecommendedIntervention.RecommendationSource.MERGED,
            validation_status=RecommendedIntervention.ValidationStatus.REJECTED,
            metadata={
                **initial_metadata,
                "rejection_reason": f"{normalized_kind!r} is unavailable in current resources",
            },
        )

    if normalized_kind in (limited_interventions or set()):
        validation_status = RecommendedIntervention.ValidationStatus.DOWNGRADED
        recommendation_source = RecommendedIntervention.RecommendationSource.MERGED
        normalization_warnings.append(
            f"{normalized_kind!r} is limited in current resources; use judiciously"
        )

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
