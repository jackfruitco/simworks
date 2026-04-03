# trainerlab/orca/schemas/initial.py

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Annotated, Any, ClassVar

from asgiref.sync import sync_to_async
from pydantic import AliasChoices, Field, model_validator
from slugify import slugify

from apps.common.outbox import event_types as outbox_events
from apps.trainerlab.adjudication import adjudicate_intervention
from apps.trainerlab.event_payloads import serialize_domain_event
from apps.trainerlab.recommendations import validate_and_normalize_recommendation
from apps.trainerlab.schemas import ScenarioBrief
from orchestrai.types import StrictBaseModel

from .types import (
    ETCO2,
    SPO2,
    AssessmentFindingSeed,
    BloodGlucoseLevel,
    BloodPressure,
    DiagnosticResultSeed,
    DispositionStateSeed,
    HeartRate,
    IllnessSeed,
    InjurySeed,
    PerformedInterventionSeed,
    ProblemSeed,
    PulseAssessmentItem,
    RecommendedInterventionSeed,
    ResourceStateSeed,
    RespiratoryRate,
)

logger = logging.getLogger(__name__)

__all__ = ["InitialScenarioSchema"]

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


if TYPE_CHECKING:
    from orchestrai_django.persistence import PersistContext


async def _passthrough(value: Any, _context: PersistContext) -> Any:
    return value


def _normalize_ref_text(value: str) -> str:
    return slugify(value or "", separator="_")


def _meaningful_ref_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _normalize_ref_text(value).split("_")
        if token and token not in _RECOMMENDATION_REF_STOPWORDS
    )


@dataclass(frozen=True)
class _RecommendationCandidate:
    seed: RecommendedInterventionSeed
    aliases: frozenset[str]
    token_sets: tuple[frozenset[str], ...]


def _build_recommendation_candidate(
    recommendation: RecommendedInterventionSeed,
) -> _RecommendationCandidate:
    alias_sources = {
        recommendation.temp_id,
        recommendation.title,
        recommendation.intervention_kind,
        f"{recommendation.intervention_kind} {recommendation.title}",
        f"{recommendation.intervention_kind} {recommendation.site}",
        f"{recommendation.intervention_kind} {recommendation.site} {recommendation.title}",
        f"{recommendation.title} {recommendation.site}",
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
    return _RecommendationCandidate(
        seed=recommendation,
        aliases=aliases,
        token_sets=token_sets,
    )


def _format_available_temp_ids(candidates: list[_RecommendationCandidate]) -> str:
    temp_ids = [candidate.seed.temp_id for candidate in candidates]
    return ", ".join(temp_ids) if temp_ids else "none"


def _format_matching_candidates(candidates: list[_RecommendationCandidate]) -> str:
    return ", ".join(
        f"{candidate.seed.temp_id} -> {candidate.seed.target_problem_ref}"
        for candidate in candidates
    )


def _find_recommendation_matches(
    *,
    raw_ref: str,
    candidates: list[_RecommendationCandidate],
) -> tuple[list[_RecommendationCandidate], bool]:
    normalized_ref = _normalize_ref_text(raw_ref)
    exact_matches = [candidate for candidate in candidates if normalized_ref in candidate.aliases]
    if exact_matches:
        return exact_matches, False

    raw_tokens = _meaningful_ref_tokens(raw_ref)
    token_matches = [
        candidate
        for candidate in candidates
        if any(
            len(token_set) >= 2 and token_set <= raw_tokens for token_set in candidate.token_sets
        )
    ]
    return token_matches, True


def _build_repaired_recommendation_seed(
    *,
    source: RecommendedInterventionSeed,
    problem: ProblemSeed,
    raw_ref: str,
    existing_temp_ids: set[str],
) -> RecommendedInterventionSeed:
    base_temp_id = _normalize_ref_text(f"{source.temp_id}_{problem.temp_id}") or "recommendation"
    temp_id = base_temp_id
    suffix = 2
    while temp_id in existing_temp_ids:
        temp_id = f"{base_temp_id}_{suffix}"
        suffix += 1

    metadata = dict(source.metadata)
    metadata["ownership_repair"] = {
        "repair_type": "cloned_from_cross_problem_reference",
        "source_temp_id": source.temp_id,
        "source_problem_ref": source.target_problem_ref,
        "source_cause_ref": source.target_cause_ref,
        "raw_ref": raw_ref,
        "repaired_problem_ref": problem.temp_id,
    }
    return source.model_copy(
        deep=True,
        update={
            "temp_id": temp_id,
            "target_problem_ref": problem.temp_id,
            "target_cause_ref": problem.cause_ref,
            "metadata": metadata,
        },
    )


def _resolve_recommendation_ref(
    *,
    problem: ProblemSeed,
    raw_ref: str,
    candidates: list[_RecommendationCandidate],
    all_candidates: list[_RecommendationCandidate],
    problems_by_ref: dict[str, ProblemSeed],
    existing_temp_ids: set[str],
) -> tuple[str, RecommendedInterventionSeed | None]:
    available_temp_ids = _format_available_temp_ids(candidates)
    normalized_ref = _normalize_ref_text(raw_ref)
    if not normalized_ref:
        raise ValueError(
            f"Problem {problem.temp_id!r} has a blank recommendation ref. "
            f"Available recommendation temp_ids for this problem: {available_temp_ids}."
        )

    local_matches, _ = _find_recommendation_matches(
        raw_ref=raw_ref,
        candidates=candidates,
    )
    if len(local_matches) == 1:
        return local_matches[0].seed.temp_id, None
    if len(local_matches) > 1:
        matching_temp_ids = ", ".join(candidate.seed.temp_id for candidate in local_matches)
        raise ValueError(
            f"Problem {problem.temp_id!r} recommendation ref {raw_ref!r} is ambiguous. "
            f"Matching recommendation temp_ids: {matching_temp_ids}. "
            f"Available recommendation temp_ids for this problem: {available_temp_ids}."
        )

    non_local_candidates = [
        candidate
        for candidate in all_candidates
        if candidate.seed.target_problem_ref != problem.temp_id
    ]
    global_matches, _ = _find_recommendation_matches(
        raw_ref=raw_ref,
        candidates=non_local_candidates,
    )
    if len(global_matches) > 1:
        matching_candidates = _format_matching_candidates(global_matches)
        raise ValueError(
            f"Problem {problem.temp_id!r} recommendation ref {raw_ref!r} is ambiguous across "
            f"problems. Matching recommendations: {matching_candidates}. "
            f"Available recommendation temp_ids for this problem: {available_temp_ids}."
        )
    if len(global_matches) == 1:
        source_candidate = global_matches[0]
        source_problem_ref = source_candidate.seed.target_problem_ref
        source_problem = problems_by_ref.get(source_problem_ref)
        if source_problem is None:
            raise ValueError(
                f"Recommendation {source_candidate.seed.temp_id!r} references unknown problem "
                f"{source_problem_ref!r}."
            )
        if source_problem.cause_ref == problem.cause_ref:
            cloned_seed = _build_repaired_recommendation_seed(
                source=source_candidate.seed,
                problem=problem,
                raw_ref=raw_ref,
                existing_temp_ids=existing_temp_ids,
            )
            logger.info(
                "TrainerLab repaired cross-problem recommendation ref for problem %s "
                "raw_ref=%s available_for_problem=%s source_recommendation=%s "
                "source_problem=%s action=cloned cloned_recommendation=%s",
                problem.temp_id,
                raw_ref,
                available_temp_ids,
                source_candidate.seed.temp_id,
                source_problem_ref,
                cloned_seed.temp_id,
            )
            return cloned_seed.temp_id, cloned_seed

        logger.warning(
            "TrainerLab rejected cross-problem recommendation ref for problem %s "
            "raw_ref=%s available_for_problem=%s source_recommendation=%s "
            "source_problem=%s action=rejected",
            problem.temp_id,
            raw_ref,
            available_temp_ids,
            source_candidate.seed.temp_id,
            source_problem_ref,
        )
        raise ValueError(
            f"Problem {problem.temp_id!r} recommendation ref {raw_ref!r} resolves to "
            f"recommendation {source_candidate.seed.temp_id!r}, but that recommendation belongs "
            f"to problem {source_problem_ref!r}. Available recommendation temp_ids for this "
            f"problem: {available_temp_ids}."
        )

    raise ValueError(
        f"Problem {problem.temp_id!r} references unknown recommendation {raw_ref!r}. "
        f"Available recommendation temp_ids for this problem: {available_temp_ids}."
    )


def _initial_extra(context: PersistContext) -> dict[str, Any]:
    return {
        "origin": "initial_scenario",
        "call_id": str(context.call_id),
        "correlation_id": context.correlation_id,
    }


def _complete_initial_generation_after_persist(context: PersistContext) -> None:
    from apps.trainerlab.services import complete_initial_scenario_generation

    logger.info(
        "TrainerLab initial generation post-persist completion handoff for simulation %s",
        context.simulation_id,
    )
    complete_initial_scenario_generation(
        simulation_id=context.simulation_id,
        correlation_id=context.correlation_id,
        call_id=str(context.call_id),
    )


class MeasurementSchemaBlock(StrictBaseModel):
    heart_rate: HeartRate
    respiratory_rate: RespiratoryRate
    spo2: SPO2
    blood_glucose_level: BloodGlucoseLevel
    blood_pressure: BloodPressure
    etco2: ETCO2 = Field(
        ...,
        validation_alias=AliasChoices("etco2", "etc02"),
        serialization_alias="etco2",
    )


CauseSchema = Annotated[InjurySeed | IllnessSeed, Field(discriminator="cause_kind")]


class InitialScenarioSchema(StrictBaseModel):
    """Initial response schema for the ORCA service."""

    scenario_brief: ScenarioBrief = Field(
        ...,
        description=(
            "Instructor-facing scenario brief that includes the read-aloud opening context and "
            "high-level environmental details."
        ),
    )
    causes: list[CauseSchema] = Field(..., min_length=1, description="Immutable cause records")
    problems: list[ProblemSeed] = Field(
        ...,
        description="Mutable actionable clinical problems, each linked to exactly one cause.",
    )
    recommended_interventions: list[RecommendedInterventionSeed] = Field(default_factory=list)
    performed_interventions: list[PerformedInterventionSeed] = Field(default_factory=list)
    assessment_findings: list[AssessmentFindingSeed] = Field(default_factory=list)
    diagnostic_results: list[DiagnosticResultSeed] = Field(default_factory=list)
    resources: list[ResourceStateSeed] = Field(default_factory=list)
    disposition: DispositionStateSeed | None = None
    measurements: MeasurementSchemaBlock = Field(..., description="Measurement schema block")
    pulses: list[PulseAssessmentItem] = Field(
        ...,
        min_length=1,
        description=(
            "Pulse assessments at anatomic sites with laterality. "
            "Include all relevant sites: radial (left/right), femoral (left/right), "
            "carotid (left/right), pedal (left/right). "
            "For each site provide present, description, color, condition, and temperature."
        ),
    )

    __persist__: ClassVar[dict[str, Any]] = {
        "scenario_brief": _passthrough,
        "causes": _passthrough,
        "problems": _passthrough,
        "recommended_interventions": _passthrough,
        "performed_interventions": _passthrough,
        "assessment_findings": _passthrough,
        "diagnostic_results": _passthrough,
        "resources": _passthrough,
        "disposition": _passthrough,
        "measurements": _passthrough,
        "pulses": _passthrough,
    }

    @model_validator(mode="after")
    def _validate_cross_references(self):
        cause_ids = [item.temp_id for item in self.causes]
        if len(cause_ids) != len(set(cause_ids)):
            raise ValueError("Cause temp_id values must be unique.")

        problem_ids = [item.temp_id for item in self.problems]
        if len(problem_ids) != len(set(problem_ids)):
            raise ValueError("Problem temp_id values must be unique.")

        recommendation_ids = [item.temp_id for item in self.recommended_interventions]
        if len(recommendation_ids) != len(set(recommendation_ids)):
            raise ValueError("Recommended intervention temp_id values must be unique.")

        finding_ids = [item.temp_id for item in self.assessment_findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("Assessment finding temp_id values must be unique.")

        diagnostic_ids = [item.temp_id for item in self.diagnostic_results]
        if len(diagnostic_ids) != len(set(diagnostic_ids)):
            raise ValueError("Diagnostic result temp_id values must be unique.")

        resource_ids = [item.temp_id for item in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("Resource temp_id values must be unique.")

        cause_refs = {item.temp_id for item in self.causes}
        problems_by_ref = {item.temp_id: item for item in self.problems}
        problem_refs = set(problems_by_ref)
        recommendations_by_problem: dict[str, list[_RecommendationCandidate]] = {}
        all_recommendation_candidates: list[_RecommendationCandidate] = []
        existing_recommendation_ids = set(recommendation_ids)
        for recommendation in self.recommended_interventions:
            candidate = _build_recommendation_candidate(recommendation)
            recommendations_by_problem.setdefault(recommendation.target_problem_ref, []).append(
                candidate
            )
            all_recommendation_candidates.append(candidate)

        for problem in self.problems:
            if problem.cause_ref not in cause_refs:
                raise ValueError(
                    f"Problem {problem.temp_id!r} references unknown cause {problem.cause_ref!r}."
                )
            normalized_refs: list[str] = []
            resolved_cache: dict[str, str] = {}
            for raw_ref in problem.recommendation_refs:
                normalized_ref = _normalize_ref_text(raw_ref)
                if normalized_ref and normalized_ref in resolved_cache:
                    normalized_refs.append(resolved_cache[normalized_ref])
                    continue
                resolved_ref, cloned_seed = _resolve_recommendation_ref(
                    problem=problem,
                    raw_ref=raw_ref,
                    candidates=recommendations_by_problem.get(problem.temp_id, []),
                    all_candidates=all_recommendation_candidates,
                    problems_by_ref=problems_by_ref,
                    existing_temp_ids=existing_recommendation_ids,
                )
                if cloned_seed is not None:
                    self.recommended_interventions.append(cloned_seed)
                    existing_recommendation_ids.add(cloned_seed.temp_id)
                    cloned_candidate = _build_recommendation_candidate(cloned_seed)
                    recommendations_by_problem.setdefault(problem.temp_id, []).append(
                        cloned_candidate
                    )
                    all_recommendation_candidates.append(cloned_candidate)
                if resolved_ref != raw_ref:
                    logger.info(
                        "Normalized TrainerLab recommendation ref for problem %s: %s -> %s",
                        problem.temp_id,
                        raw_ref,
                        resolved_ref,
                    )
                if normalized_ref:
                    resolved_cache[normalized_ref] = resolved_ref
                normalized_refs.append(resolved_ref)
            problem.recommendation_refs = normalized_refs

        for recommendation in self.recommended_interventions:
            if recommendation.target_problem_ref not in problem_refs:
                raise ValueError(
                    f"Recommendation {recommendation.temp_id!r} references unknown problem "
                    f"{recommendation.target_problem_ref!r}."
                )
            if (
                recommendation.target_cause_ref
                and recommendation.target_cause_ref not in cause_refs
            ):
                raise ValueError(
                    f"Recommendation {recommendation.temp_id!r} references unknown cause "
                    f"{recommendation.target_cause_ref!r}."
                )

        for performed in self.performed_interventions:
            if performed.target_problem_ref not in problem_refs:
                raise ValueError(
                    "Performed intervention references an unknown target_problem_ref: "
                    f"{performed.target_problem_ref!r}."
                )

        for finding in self.assessment_findings:
            if finding.target_problem_ref and finding.target_problem_ref not in problem_refs:
                raise ValueError(
                    f"Assessment finding {finding.temp_id!r} references unknown problem "
                    f"{finding.target_problem_ref!r}."
                )

        for diagnostic in self.diagnostic_results:
            if diagnostic.target_problem_ref and diagnostic.target_problem_ref not in problem_refs:
                raise ValueError(
                    f"Diagnostic result {diagnostic.temp_id!r} references unknown problem "
                    f"{diagnostic.target_problem_ref!r}."
                )
        return self

    async def post_persist(self, _results: dict[str, Any], context: PersistContext) -> None:
        from apps.common.outbox.helpers import broadcast_domain_objects
        from apps.trainerlab.models import (
            ETCO2 as ETCO2Model,
            SPO2 as SPO2Model,
            AssessmentFinding,
            BloodGlucoseLevel as BloodGlucoseModel,
            BloodPressure as BloodPressureModel,
            DiagnosticResult,
            DispositionState,
            EventSource,
            HeartRate as HeartRateModel,
            Illness,
            Injury,
            Intervention,
            Problem,
            PulseAssessment,
            RecommendationEvaluation,
            RecommendedIntervention,
            ResourceState,
            RespiratoryRate as RespiratoryRateModel,
            ScenarioBrief as ScenarioBriefModel,
            TrainerSession,
        )
        from apps.trainerlab.services import (
            commit_non_ai_mutation_side_effects,
        )

        allow_seeded_performed = bool(context.extra.get("allow_seeded_performed_interventions"))
        if self.performed_interventions and not allow_seeded_performed:
            raise ValueError(
                "Initial scenario generation may not create performed interventions unless the "
                "context explicitly allows trusted seeded interventions."
            )

        scenario_brief_payload = self.scenario_brief.model_dump(mode="json")
        scenario_brief_obj = await ScenarioBriefModel.objects.acreate(
            simulation_id=context.simulation_id,
            source=EventSource.AI,
            **scenario_brief_payload,
        )

        measurement_payload = self.measurements.model_dump(mode="json")
        vital_model_map = {
            "heart_rate": HeartRateModel,
            "respiratory_rate": RespiratoryRateModel,
            "spo2": SPO2Model,
            "blood_glucose_level": BloodGlucoseModel,
            "blood_pressure": BloodPressureModel,
            "etco2": ETCO2Model,
        }
        vital_objects: list[Any] = []
        for key, model_cls in vital_model_map.items():
            payload = dict(measurement_payload[key])
            vital_objects.append(
                await model_cls.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.AI,
                    **payload,
                )
            )

        pulse_objects = [
            await PulseAssessment.objects.acreate(
                simulation_id=context.simulation_id,
                source=EventSource.AI,
                **pulse_item.model_dump(mode="json"),
            )
            for pulse_item in self.pulses
        ]

        causes_by_ref: dict[str, Injury | Illness] = {}
        injury_objects: list[Injury] = []
        illness_objects: list[Illness] = []
        for cause_seed in self.causes:
            if isinstance(cause_seed, InjurySeed):
                cause_obj = await Injury.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.AI,
                    injury_location=cause_seed.injury_location,
                    injury_kind=cause_seed.injury_kind,
                    injury_description=cause_seed.injury_description,
                    kind=cause_seed.kind,
                    code=cause_seed.code,
                    slug=cause_seed.kind,
                    title=cause_seed.title,
                    display_name=cause_seed.display_name,
                    description=cause_seed.description,
                    anatomical_location=cause_seed.anatomical_location,
                    laterality=cause_seed.laterality,
                    metadata_json=cause_seed.metadata,
                )
                injury_objects.append(cause_obj)
            else:
                cause_obj = await Illness.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.AI,
                    name=cause_seed.name,
                    description=cause_seed.description,
                    kind=cause_seed.kind,
                    code=cause_seed.code,
                    slug=cause_seed.kind,
                    title=cause_seed.title,
                    display_name=cause_seed.display_name,
                    anatomical_location=cause_seed.anatomical_location,
                    laterality=cause_seed.laterality,
                    metadata_json=cause_seed.metadata,
                )
                illness_objects.append(cause_obj)
            causes_by_ref[cause_seed.temp_id] = cause_obj

        problems_by_ref: dict[str, Problem] = {}
        problem_objects: list[Problem] = []
        for problem_seed in self.problems:
            cause_obj = causes_by_ref[problem_seed.cause_ref]
            problem = await Problem.objects.acreate(
                simulation_id=context.simulation_id,
                source=EventSource.AI,
                cause_injury=cause_obj if isinstance(cause_obj, Injury) else None,
                cause_illness=cause_obj if isinstance(cause_obj, Illness) else None,
                problem_kind=(
                    Problem.ProblemKind.INJURY
                    if isinstance(cause_obj, Injury)
                    else Problem.ProblemKind.ILLNESS
                ),
                kind=problem_seed.kind,
                code=problem_seed.code,
                slug=problem_seed.kind,
                title=problem_seed.title,
                display_name=problem_seed.display_name,
                description=problem_seed.description,
                march_category=problem_seed.march_category or Problem.MARCHCategory.C,
                severity=problem_seed.severity,
                anatomical_location=problem_seed.anatomical_location,
                laterality=problem_seed.laterality,
                status=problem_seed.initial_status,
            )
            problem_objects.append(problem)
            problems_by_ref[problem_seed.temp_id] = problem

        finding_objects: list[AssessmentFinding] = []
        for finding_seed in self.assessment_findings:
            target_problem = (
                problems_by_ref[finding_seed.target_problem_ref]
                if finding_seed.target_problem_ref
                else None
            )
            finding_objects.append(
                await AssessmentFinding.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.AI,
                    kind=finding_seed.finding_kind,
                    code=finding_seed.finding_kind,
                    slug=finding_seed.finding_kind,
                    title=finding_seed.title,
                    display_name=finding_seed.title,
                    description=finding_seed.description,
                    status=finding_seed.status,
                    severity=finding_seed.severity,
                    target_problem=target_problem,
                    anatomical_location=finding_seed.anatomical_location,
                    laterality=finding_seed.laterality,
                    metadata_json=finding_seed.metadata,
                )
            )

        diagnostic_objects: list[DiagnosticResult] = []
        for diagnostic_seed in self.diagnostic_results:
            target_problem = (
                problems_by_ref[diagnostic_seed.target_problem_ref]
                if diagnostic_seed.target_problem_ref
                else None
            )
            diagnostic_objects.append(
                await DiagnosticResult.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.AI,
                    kind=diagnostic_seed.diagnostic_kind,
                    code=diagnostic_seed.diagnostic_kind,
                    slug=diagnostic_seed.diagnostic_kind,
                    title=diagnostic_seed.title,
                    display_name=diagnostic_seed.title,
                    description=diagnostic_seed.description,
                    status=diagnostic_seed.status,
                    value_text=diagnostic_seed.value_text,
                    target_problem=target_problem,
                    metadata_json=diagnostic_seed.metadata,
                )
            )

        resource_objects: list[ResourceState] = []
        for resource_seed in self.resources:
            resource_objects.append(
                await ResourceState.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.AI,
                    kind=resource_seed.kind,
                    code=resource_seed.code,
                    slug=resource_seed.kind,
                    title=resource_seed.title,
                    display_name=resource_seed.display_name,
                    status=resource_seed.status,
                    quantity_available=resource_seed.quantity_available,
                    quantity_unit=resource_seed.quantity_unit,
                    description=resource_seed.description,
                    metadata_json=resource_seed.metadata,
                )
            )

        disposition_obj = None
        if self.disposition is not None:
            disposition_obj = await DispositionState.objects.acreate(
                simulation_id=context.simulation_id,
                source=EventSource.AI,
                status=self.disposition.status,
                transport_mode=self.disposition.transport_mode,
                destination=self.disposition.destination,
                eta_minutes=self.disposition.eta_minutes,
                handoff_ready=self.disposition.handoff_ready,
                scene_constraints_json=self.disposition.scene_constraints,
                metadata_json=self.disposition.metadata,
            )

        contraindicated_interventions = {
            str(item)
            for obj in [*finding_objects, *diagnostic_objects]
            for item in obj.metadata_json.get("contraindicated_interventions", [])
        }
        unavailable_interventions: set[str] = set()
        limited_interventions: set[str] = set()
        for resource in resource_objects:
            code = resource.code or resource.kind
            if (
                resource.status in {ResourceState.Status.UNAVAILABLE, ResourceState.Status.DEPLETED}
                or resource.quantity_available <= 0
            ):
                unavailable_interventions.add(code)
            elif (
                resource.status == ResourceState.Status.LIMITED or resource.quantity_available <= 1
            ):
                limited_interventions.add(code)

        recommendation_objects: list[RecommendedIntervention] = []
        recommendation_evaluations: list[RecommendationEvaluation] = []
        for recommendation_seed in self.recommended_interventions:
            problem = problems_by_ref[recommendation_seed.target_problem_ref]
            normalization = validate_and_normalize_recommendation(
                problem=problem,
                raw_kind=recommendation_seed.intervention_kind,
                raw_title=recommendation_seed.title,
                raw_site=recommendation_seed.site,
                rationale=recommendation_seed.rationale,
                priority=recommendation_seed.priority,
                warnings=recommendation_seed.warnings,
                contraindications=recommendation_seed.contraindications,
                metadata=recommendation_seed.metadata,
                contraindicated_interventions=contraindicated_interventions,
                unavailable_interventions=unavailable_interventions,
                limited_interventions=limited_interventions,
            )
            cause_obj = (
                causes_by_ref[recommendation_seed.target_cause_ref]
                if recommendation_seed.target_cause_ref
                else problem.cause
            )
            if not normalization.accepted:
                logger.info(
                    "Rejected TrainerLab recommendation %s for problem %s: %s",
                    recommendation_seed.temp_id,
                    problem.id,
                    normalization.metadata.get("rejection_reason"),
                )
                recommendation_evaluations.append(
                    await RecommendationEvaluation.objects.acreate(
                        simulation_id=context.simulation_id,
                        source=EventSource.SYSTEM,
                        target_problem=problem,
                        target_injury=cause_obj if isinstance(cause_obj, Injury) else None,
                        target_illness=cause_obj if isinstance(cause_obj, Illness) else None,
                        raw_kind=recommendation_seed.intervention_kind,
                        raw_title=recommendation_seed.title,
                        raw_site=recommendation_seed.site,
                        normalized_kind=normalization.kind,
                        normalized_code=normalization.code,
                        title=normalization.title or recommendation_seed.title,
                        recommendation_source=normalization.recommendation_source,
                        validation_status=normalization.validation_status,
                        rationale=normalization.rationale,
                        priority=normalization.priority,
                        warnings_json=normalization.warnings,
                        contraindications_json=normalization.contraindications,
                        rejection_reason=str(normalization.metadata.get("rejection_reason", "")),
                        metadata_json=normalization.metadata,
                    )
                )
                continue
            recommendation = await RecommendedIntervention.objects.acreate(
                simulation_id=context.simulation_id,
                source=EventSource.AI,
                kind=normalization.kind,
                code=normalization.code,
                slug=normalization.slug,
                title=normalization.title,
                display_name=normalization.display_name,
                description="",
                target_problem=problem,
                target_injury=cause_obj if isinstance(cause_obj, Injury) else None,
                target_illness=cause_obj if isinstance(cause_obj, Illness) else None,
                recommendation_source=normalization.recommendation_source,
                validation_status=normalization.validation_status,
                normalized_kind=normalization.kind,
                normalized_code=normalization.code,
                rationale=normalization.rationale,
                priority=normalization.priority,
                site_code=normalization.site_code,
                site_label=normalization.site_label,
                contraindications_json=normalization.contraindications,
                warnings_json=normalization.warnings,
                metadata_json=normalization.metadata,
            )
            recommendation_objects.append(recommendation)
            recommendation_evaluations.append(
                await RecommendationEvaluation.objects.acreate(
                    simulation_id=context.simulation_id,
                    source=EventSource.SYSTEM,
                    recommendation=recommendation,
                    target_problem=problem,
                    target_injury=cause_obj if isinstance(cause_obj, Injury) else None,
                    target_illness=cause_obj if isinstance(cause_obj, Illness) else None,
                    raw_kind=recommendation_seed.intervention_kind,
                    raw_title=recommendation_seed.title,
                    raw_site=recommendation_seed.site,
                    normalized_kind=normalization.kind,
                    normalized_code=normalization.code,
                    title=normalization.title,
                    recommendation_source=normalization.recommendation_source,
                    validation_status=normalization.validation_status,
                    rationale=normalization.rationale,
                    priority=normalization.priority,
                    warnings_json=normalization.warnings,
                    contraindications_json=normalization.contraindications,
                    metadata_json=normalization.metadata,
                )
            )

        intervention_objects: list[Intervention] = []
        for performed_seed in self.performed_interventions:
            target_problem = problems_by_ref[performed_seed.target_problem_ref]
            intervention = await Intervention.objects.acreate(
                simulation_id=context.simulation_id,
                source=EventSource.SYSTEM,
                intervention_type=performed_seed.intervention_kind,
                site_code=performed_seed.site,
                target_problem=target_problem,
                notes=performed_seed.notes,
                details_json=performed_seed.details,
                initiated_by_type=performed_seed.initiated_by_type,
                initiated_by_id=performed_seed.initiated_by_id,
            )
            await sync_to_async(adjudicate_intervention)(intervention)
            intervention_objects.append(intervention)

        extra = _initial_extra(context)

        await broadcast_domain_objects(
            event_type=outbox_events.SIMULATION_BRIEF_CREATED,
            objects=[scenario_brief_obj],
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )

        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_INJURY_CREATED,
            objects=injury_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_ILLNESS_CREATED,
            objects=illness_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_PROBLEM_CREATED,
            objects=problem_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_ASSESSMENT_FINDING_CREATED,
            objects=finding_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_DIAGNOSTIC_RESULT_CREATED,
            objects=diagnostic_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_RESOURCE_UPDATED,
            objects=resource_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        if disposition_obj is not None:
            await broadcast_domain_objects(
                event_type=outbox_events.PATIENT_DISPOSITION_UPDATED,
                objects=[disposition_obj],
                context=context,
                payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
            )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_RECOMMENDED_INTERVENTION_CREATED,
            objects=recommendation_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_RECOMMENDATION_EVALUATION_CREATED,
            objects=recommendation_evaluations,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_INTERVENTION_CREATED,
            objects=intervention_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_VITAL_CREATED,
            objects=vital_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type=outbox_events.PATIENT_PULSE_CREATED,
            objects=pulse_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )

        session = (
            await TrainerSession.objects.select_related("simulation")
            .filter(simulation_id=context.simulation_id)
            .afirst()
        )
        if session is not None:
            await sync_to_async(commit_non_ai_mutation_side_effects, thread_sensitive=True)(
                session=session,
                event_kind="initial_seed",
                correlation_id=context.correlation_id,
                worker_kind="initial_seed",
                domains=["physiology", "causes", "problems", "recommendations"],
                source_call_id=str(context.call_id),
            )
            await sync_to_async(_complete_initial_generation_after_persist, thread_sensitive=True)(
                context
            )
