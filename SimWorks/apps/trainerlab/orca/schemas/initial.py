# trainerlab/orca/schemas/initial.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any, ClassVar

from asgiref.sync import sync_to_async
from pydantic import AliasChoices, Field, model_validator

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


if TYPE_CHECKING:
    from orchestrai_django.persistence import PersistContext


async def _passthrough(value: Any, _context: PersistContext) -> Any:
    return value


def _initial_extra(context: PersistContext) -> dict[str, Any]:
    return {
        "origin": "initial_scenario",
        "call_id": str(context.call_id),
        "correlation_id": context.correlation_id,
    }


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
        recommendation_refs = {item.temp_id for item in self.recommended_interventions}
        problem_refs = {item.temp_id for item in self.problems}

        for problem in self.problems:
            if problem.cause_ref not in cause_refs:
                raise ValueError(
                    f"Problem {problem.temp_id!r} references unknown cause {problem.cause_ref!r}."
                )
            missing_recommendations = [
                ref for ref in problem.recommendation_refs if ref not in recommendation_refs
            ]
            if missing_recommendations:
                raise ValueError(
                    f"Problem {problem.temp_id!r} references unknown recommendations: "
                    f"{', '.join(missing_recommendations)}."
                )

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
