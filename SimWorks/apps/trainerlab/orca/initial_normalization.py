from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
from typing import Any

from slugify import slugify

logger = logging.getLogger(__name__)

_RECOMMENDATION_REF_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "after",
        "for",
        "if",
        "of",
        "on",
        "or",
        "recommendation",
        "recommendations",
        "recommended",
        "the",
        "to",
    }
)


@dataclass(frozen=True)
class RecommendationCandidate:
    recommendation: dict[str, Any]
    aliases: frozenset[str]
    token_sets: tuple[frozenset[str], ...]

    @property
    def temp_id(self) -> str:
        return str(self.recommendation.get("temp_id") or "")

    @property
    def target_problem_ref(self) -> str:
        return str(self.recommendation.get("target_problem_ref") or "")


def _normalize_ref_text(value: str) -> str:
    return slugify(value or "", separator="_")


def _meaningful_ref_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _normalize_ref_text(value).split("_")
        if token and token not in _RECOMMENDATION_REF_STOPWORDS
    )


def _build_recommendation_candidate(recommendation: dict[str, Any]) -> RecommendationCandidate:
    temp_id = str(recommendation.get("temp_id") or "")
    title = str(recommendation.get("title") or "")
    intervention_kind = str(recommendation.get("intervention_kind") or "")
    site = str(recommendation.get("site") or "")
    alias_sources = {
        temp_id,
        title,
        intervention_kind,
        f"{intervention_kind} {title}",
        f"{intervention_kind} {site}",
        f"{intervention_kind} {site} {title}",
        f"{title} {site}",
    }
    aliases = frozenset(
        normalized
        for normalized in (_normalize_ref_text(value) for value in alias_sources)
        if normalized
    )
    token_sets = tuple(
        sorted_token_sets
        for sorted_token_sets in {
            _meaningful_ref_tokens(value)
            for value in alias_sources
            if _meaningful_ref_tokens(value)
        }
    )
    return RecommendationCandidate(
        recommendation=recommendation,
        aliases=aliases,
        token_sets=token_sets,
    )


def _format_available_temp_ids(candidates: list[RecommendationCandidate]) -> str:
    temp_ids = [candidate.temp_id for candidate in candidates]
    return ", ".join(temp_ids) if temp_ids else "none"


def _format_matching_candidates(candidates: list[RecommendationCandidate]) -> str:
    return ", ".join(
        f"{candidate.temp_id} -> {candidate.target_problem_ref}" for candidate in candidates
    )


def _find_recommendation_matches(
    *,
    raw_ref: str,
    candidates: list[RecommendationCandidate],
) -> list[RecommendationCandidate]:
    normalized_ref = _normalize_ref_text(raw_ref)
    exact_matches = [candidate for candidate in candidates if normalized_ref in candidate.aliases]
    if exact_matches:
        return exact_matches

    raw_tokens = _meaningful_ref_tokens(raw_ref)
    return [
        candidate
        for candidate in candidates
        if any(
            len(token_set) >= 2 and token_set <= raw_tokens for token_set in candidate.token_sets
        )
    ]


def _build_cloned_recommendation(
    *,
    source: dict[str, Any],
    problem: dict[str, Any],
    raw_ref: str,
    existing_temp_ids: set[str],
) -> dict[str, Any]:
    source_temp_id = str(source.get("temp_id") or "")
    problem_temp_id = str(problem.get("temp_id") or "")
    base_temp_id = _normalize_ref_text(f"{source_temp_id}_{problem_temp_id}") or "recommendation"
    temp_id = base_temp_id
    suffix = 2
    while temp_id in existing_temp_ids:
        temp_id = f"{base_temp_id}_{suffix}"
        suffix += 1

    cloned = deepcopy(source)
    metadata = dict(cloned.get("metadata") or {})
    metadata["ownership_repair"] = {
        "repair_type": "cloned_from_cross_problem_reference",
        "source_temp_id": source_temp_id,
        "source_problem_ref": source.get("target_problem_ref"),
        "source_cause_ref": source.get("target_cause_ref"),
        "raw_ref": raw_ref,
        "repaired_problem_ref": problem_temp_id,
    }
    cloned["temp_id"] = temp_id
    cloned["target_problem_ref"] = problem_temp_id
    cloned["target_cause_ref"] = problem.get("cause_ref")
    cloned["metadata"] = metadata
    return cloned


def normalize_initial_scenario_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply explicit tactical repair for recommendation ownership mismatches.

    Policy:
    - Recommendation refs are problem-local.
    - If a ref uniquely resolves to another problem's recommendation and both problems share the
      same `cause_ref`, clone that recommendation into a new problem-owned recommendation.
    - Cross-cause reuse remains invalid and is rejected.
    """

    normalized = deepcopy(payload)
    problems = normalized.get("problems")
    recommendations = normalized.get("recommended_interventions")
    if not isinstance(problems, list) or not isinstance(recommendations, list):
        return normalized

    problems_by_ref = {
        str(problem.get("temp_id") or ""): problem
        for problem in problems
        if isinstance(problem, dict) and problem.get("temp_id")
    }
    recommendations_by_problem: dict[str, list[RecommendationCandidate]] = {}
    all_candidates: list[RecommendationCandidate] = []
    existing_temp_ids: set[str] = set()
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        candidate = _build_recommendation_candidate(recommendation)
        recommendations_by_problem.setdefault(candidate.target_problem_ref, []).append(candidate)
        all_candidates.append(candidate)
        if candidate.temp_id:
            existing_temp_ids.add(candidate.temp_id)

    for problem in problems:
        if not isinstance(problem, dict):
            continue
        problem_temp_id = str(problem.get("temp_id") or "")
        problem_cause_ref = str(problem.get("cause_ref") or "")
        raw_refs = problem.get("recommendation_refs")
        if not isinstance(raw_refs, list):
            continue
        normalized_refs: list[str] = []
        resolved_cache: dict[str, str] = {}
        for raw_ref in raw_refs:
            raw_ref_text = str(raw_ref or "")
            local_candidates = recommendations_by_problem.get(problem_temp_id, [])
            available_temp_ids = _format_available_temp_ids(local_candidates)
            normalized_ref = _normalize_ref_text(raw_ref_text)
            if not normalized_ref:
                raise ValueError(
                    f"Problem {problem_temp_id!r} has a blank recommendation ref. "
                    f"Available recommendation temp_ids for this problem: {available_temp_ids}."
                )
            if normalized_ref in resolved_cache:
                normalized_refs.append(resolved_cache[normalized_ref])
                continue

            local_matches = _find_recommendation_matches(
                raw_ref=raw_ref_text,
                candidates=local_candidates,
            )
            if len(local_matches) == 1:
                resolved_cache[normalized_ref] = local_matches[0].temp_id
                normalized_refs.append(local_matches[0].temp_id)
                continue
            if len(local_matches) > 1:
                matching_temp_ids = ", ".join(candidate.temp_id for candidate in local_matches)
                raise ValueError(
                    f"Problem {problem_temp_id!r} recommendation ref {raw_ref_text!r} is ambiguous. "
                    f"Matching recommendation temp_ids: {matching_temp_ids}. "
                    f"Available recommendation temp_ids for this problem: {available_temp_ids}."
                )

            global_matches = _find_recommendation_matches(
                raw_ref=raw_ref_text,
                candidates=[
                    candidate
                    for candidate in all_candidates
                    if candidate.target_problem_ref != problem_temp_id
                ],
            )
            if len(global_matches) > 1:
                raise ValueError(
                    f"Problem {problem_temp_id!r} recommendation ref {raw_ref_text!r} is ambiguous across "
                    f"problems. Matching recommendations: {_format_matching_candidates(global_matches)}. "
                    f"Available recommendation temp_ids for this problem: {available_temp_ids}."
                )
            if len(global_matches) == 1:
                source_candidate = global_matches[0]
                source_problem_ref = source_candidate.target_problem_ref
                source_problem = problems_by_ref.get(source_problem_ref)
                if (
                    source_problem
                    and str(source_problem.get("cause_ref") or "") == problem_cause_ref
                ):
                    cloned = _build_cloned_recommendation(
                        source=source_candidate.recommendation,
                        problem=problem,
                        raw_ref=raw_ref_text,
                        existing_temp_ids=existing_temp_ids,
                    )
                    recommendations.append(cloned)
                    cloned_candidate = _build_recommendation_candidate(cloned)
                    recommendations_by_problem.setdefault(problem_temp_id, []).append(
                        cloned_candidate
                    )
                    all_candidates.append(cloned_candidate)
                    existing_temp_ids.add(cloned_candidate.temp_id)
                    logger.info(
                        "TrainerLab normalized cross-problem recommendation ref for problem %s "
                        "raw_ref=%s available_for_problem=%s source_recommendation=%s "
                        "source_problem=%s action=cloned cloned_recommendation=%s",
                        problem_temp_id,
                        raw_ref_text,
                        available_temp_ids,
                        source_candidate.temp_id,
                        source_problem_ref,
                        cloned_candidate.temp_id,
                    )
                    resolved_cache[normalized_ref] = cloned_candidate.temp_id
                    normalized_refs.append(cloned_candidate.temp_id)
                    continue

                logger.warning(
                    "TrainerLab normalized cross-problem recommendation ref for problem %s "
                    "raw_ref=%s available_for_problem=%s source_recommendation=%s "
                    "source_problem=%s action=rejected",
                    problem_temp_id,
                    raw_ref_text,
                    available_temp_ids,
                    source_candidate.temp_id,
                    source_problem_ref,
                )
                raise ValueError(
                    f"Problem {problem_temp_id!r} recommendation ref {raw_ref_text!r} resolves to "
                    f"recommendation {source_candidate.temp_id!r}, but that recommendation belongs "
                    f"to problem {source_problem_ref!r}. Available recommendation temp_ids for this "
                    f"problem: {available_temp_ids}."
                )

            raise ValueError(
                f"Problem {problem_temp_id!r} references unknown recommendation {raw_ref_text!r}. "
                f"Available recommendation temp_ids for this problem: {available_temp_ids}."
            )

        problem["recommendation_refs"] = normalized_refs

    return normalized
