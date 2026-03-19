from __future__ import annotations

from dataclasses import dataclass

from slugify import slugify

from .intervention_dictionary import get_intervention_site_label
from .models import Intervention, Problem


def _tokenize(value: str) -> set[str]:
    return {token for token in slugify(value or "", separator="_").split("_") if token}


def _problem_location_tokens(problem: Problem) -> set[str]:
    tokens = _tokenize(problem.anatomical_location)
    tokens.update(_tokenize(problem.display_name))
    tokens.update(_tokenize(problem.title))
    cause = problem.cause
    if cause is not None:
        tokens.update(_tokenize(getattr(cause, "anatomical_location", "")))
        tokens.update(_tokenize(getattr(cause, "display_name", "")))
        tokens.update(_tokenize(getattr(cause, "title", "")))
        tokens.update(_tokenize(getattr(cause, "description", "")))
    return tokens


def _site_matches_problem(*, problem: Problem, intervention: Intervention) -> bool:
    if not intervention.site_code:
        return True
    site_label = get_intervention_site_label(intervention.intervention_type, intervention.site_code)
    site_tokens = _tokenize(site_label) | _tokenize(intervention.site_code)
    problem_tokens = _problem_location_tokens(problem)
    if not site_tokens or not problem_tokens:
        return True

    laterality_tokens = {"left", "right"} & site_tokens
    if laterality_tokens and not laterality_tokens <= problem_tokens:
        return False

    anatomy_map = {
        "arm": {"arm", "upper", "lower", "extremity"},
        "leg": {"leg", "thigh", "lower", "extremity"},
        "chest": {"chest", "thorax"},
        "axilla": {"axilla", "axillary"},
        "inguinal": {"inguinal", "groin"},
        "neck": {"neck"},
    }
    for anchor, aliases in anatomy_map.items():
        if anchor in site_tokens and not (aliases & problem_tokens):
            return False
    return True


def _status_rank(value: str) -> int:
    order = {
        Problem.Status.ACTIVE: 0,
        Problem.Status.TREATED: 1,
        Problem.Status.CONTROLLED: 2,
        Problem.Status.RESOLVED: 3,
    }
    return order[value]


def _promote_status(current: str, desired: str) -> str:
    if _status_rank(desired) > _status_rank(current):
        return desired
    return current


@dataclass(frozen=True)
class AdjudicationResult:
    changed: bool
    previous_status: str
    current_status: str
    reason: str = ""
    rule_id: str = ""


_INTERVENTION_STATUS_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "tourniquet": (("hemorrhage", Problem.Status.CONTROLLED),),
    "junctional_tourniquet": (("hemorrhage", Problem.Status.CONTROLLED),),
    "wound_packing": (("hemorrhage", Problem.Status.CONTROLLED),),
    "hemostatic_agent": (("hemorrhage", Problem.Status.TREATED),),
    "pressure_dressing": (
        ("hemorrhage", Problem.Status.TREATED),
        ("open_wound", Problem.Status.TREATED),
    ),
    "chest_seal": (("open_chest_wound", Problem.Status.CONTROLLED),),
    "needle_decompression": (("tension_pneumothorax", Problem.Status.CONTROLLED),),
    "chest_tube": (("tension_pneumothorax", Problem.Status.CONTROLLED),),
    "antibiotics": (("infectious_process", Problem.Status.TREATED),),
}


def adjudicate_intervention(intervention: Intervention) -> AdjudicationResult:
    problem = intervention.target_problem
    previous_status = problem.status
    rules = _INTERVENTION_STATUS_RULES.get(intervention.intervention_type, ())
    matching_status = next((status for kind, status in rules if kind == problem.kind), None)
    if matching_status is None:
        intervention.target_problem_previous_status = previous_status
        intervention.target_problem_current_status = previous_status
        intervention.adjudication_reason = "intervention_not_applicable_to_problem_kind"
        intervention.adjudication_rule_id = ""
        intervention.save(
            update_fields=[
                "target_problem_previous_status",
                "target_problem_current_status",
                "adjudication_reason",
                "adjudication_rule_id",
            ]
        )
        return AdjudicationResult(
            changed=False,
            previous_status=previous_status,
            current_status=previous_status,
            reason="intervention_not_applicable_to_problem_kind",
        )

    if not _site_matches_problem(problem=problem, intervention=intervention):
        intervention.target_problem_previous_status = previous_status
        intervention.target_problem_current_status = previous_status
        intervention.adjudication_reason = "intervention_site_does_not_match_problem"
        intervention.adjudication_rule_id = ""
        intervention.save(
            update_fields=[
                "target_problem_previous_status",
                "target_problem_current_status",
                "adjudication_reason",
                "adjudication_rule_id",
            ]
        )
        return AdjudicationResult(
            changed=False,
            previous_status=previous_status,
            current_status=previous_status,
            reason="intervention_site_does_not_match_problem",
        )

    rule_id = f"intervention.{intervention.intervention_type}.targets.{problem.kind}"
    next_status = _promote_status(problem.status, matching_status)
    if next_status == problem.status:
        intervention.target_problem_previous_status = previous_status
        intervention.target_problem_current_status = previous_status
        intervention.adjudication_reason = "problem_status_already_at_or_beyond_rule"
        intervention.adjudication_rule_id = rule_id
        intervention.save(
            update_fields=[
                "target_problem_previous_status",
                "target_problem_current_status",
                "adjudication_reason",
                "adjudication_rule_id",
            ]
        )
        return AdjudicationResult(
            changed=False,
            previous_status=previous_status,
            current_status=previous_status,
            reason="problem_status_already_at_or_beyond_rule",
            rule_id=rule_id,
        )

    problem.is_active = False
    problem.save(update_fields=["is_active"])
    superseding_problem = Problem.objects.create(
        simulation=problem.simulation,
        source=problem.source,
        supersedes=problem,
        cause_injury=problem.cause_injury,
        cause_illness=problem.cause_illness,
        parent_problem=problem.parent_problem,
        problem_kind=problem.problem_kind,
        kind=problem.kind,
        code=problem.code,
        slug=problem.slug,
        title=problem.title,
        display_name=problem.display_name,
        description=problem.description,
        march_category=problem.march_category,
        severity=problem.severity,
        anatomical_location=problem.anatomical_location,
        laterality=problem.laterality,
        status=next_status,
        previous_status=previous_status,
        triggering_intervention=intervention,
        adjudication_reason="intervention_adjudicated",
        adjudication_rule_id=rule_id,
        metadata_json=problem.metadata_json,
    )
    intervention.target_problem = superseding_problem
    intervention.target_problem_previous_status = previous_status
    intervention.target_problem_current_status = superseding_problem.status
    intervention.adjudication_reason = "intervention_adjudicated"
    intervention.adjudication_rule_id = rule_id
    intervention.save(
        update_fields=[
            "target_problem",
            "target_problem_previous_status",
            "target_problem_current_status",
            "adjudication_reason",
            "adjudication_rule_id",
        ]
    )
    return AdjudicationResult(
        changed=True,
        previous_status=previous_status,
        current_status=superseding_problem.status,
        reason="intervention_adjudicated",
        rule_id=rule_id,
    )
