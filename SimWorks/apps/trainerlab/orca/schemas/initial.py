# trainerlab/orca/schemas/initial.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any, ClassVar

from asgiref.sync import sync_to_async
from pydantic import AliasChoices, Field, model_validator

from apps.trainerlab.adjudication import adjudicate_intervention
from apps.trainerlab.event_payloads import serialize_domain_event
from apps.trainerlab.recommendations import validate_and_normalize_recommendation
from apps.trainerlab.schemas import ScenarioBrief
from orchestrai.types import StrictBaseModel

from .types import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    IllnessSeed,
    InjurySeed,
    PerformedInterventionSeed,
    ProblemSeed,
    PulseAssessmentItem,
    RecommendedInterventionSeed,
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
        return self

    async def post_persist(self, _results: dict[str, Any], context: PersistContext) -> None:
        from apps.common.outbox.helpers import broadcast_domain_objects
        from apps.trainerlab.models import (
            ETCO2 as ETCO2Model,
            SPO2 as SPO2Model,
            BloodGlucoseLevel as BloodGlucoseModel,
            BloodPressure as BloodPressureModel,
            EventSource,
            HeartRate as HeartRateModel,
            Illness,
            Injury,
            Intervention,
            Problem,
            PulseAssessment,
            RecommendedIntervention,
            RespiratoryRate as RespiratoryRateModel,
            ScenarioBrief as ScenarioBriefModel,
        )
        from apps.trainerlab.services import refresh_projection_from_domain_state

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

        recommendation_objects: list[RecommendedIntervention] = []
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
            )
            if not normalization.accepted:
                logger.info(
                    "Rejected TrainerLab recommendation %s for problem %s: %s",
                    recommendation_seed.temp_id,
                    problem.id,
                    normalization.metadata.get("rejection_reason"),
                )
                continue
            cause_obj = (
                causes_by_ref[recommendation_seed.target_cause_ref]
                if recommendation_seed.target_cause_ref
                else problem.cause
            )
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

        recommendations_by_problem_id: dict[int, list[RecommendedIntervention]] = {}
        recommendations_by_cause_key: dict[tuple[str, int], list[RecommendedIntervention]] = {}
        for recommendation in recommendation_objects:
            recommendations_by_problem_id.setdefault(recommendation.target_problem_id, []).append(
                recommendation
            )
            if recommendation.target_injury_id:
                recommendations_by_cause_key.setdefault(
                    ("injury", recommendation.target_injury_id), []
                ).append(recommendation)
            elif recommendation.target_illness_id:
                recommendations_by_cause_key.setdefault(
                    ("illness", recommendation.target_illness_id), []
                ).append(recommendation)

        for problem in problem_objects:
            problem._prefetched_objects_cache = {
                "recommended_interventions": recommendations_by_problem_id.get(problem.id, [])
            }
        for injury in injury_objects:
            injury._prefetched_objects_cache = {
                "recommended_interventions": recommendations_by_cause_key.get(
                    ("injury", injury.id), []
                )
            }
        for illness in illness_objects:
            illness._prefetched_objects_cache = {
                "recommended_interventions": recommendations_by_cause_key.get(
                    ("illness", illness.id), []
                )
            }

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
            event_type="trainerlab.scenario_brief.created",
            objects=[scenario_brief_obj],
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )

        await broadcast_domain_objects(
            event_type="injury.created",
            objects=injury_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type="illness.created",
            objects=illness_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type="problem.created",
            objects=problem_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type="recommended_intervention.created",
            objects=recommendation_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type="intervention.created",
            objects=intervention_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type="trainerlab.vital.created",
            objects=vital_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )
        await broadcast_domain_objects(
            event_type="trainerlab.pulse.created",
            objects=pulse_objects,
            context=context,
            payload_builder=lambda obj: serialize_domain_event(obj, extra=extra),
        )

        await sync_to_async(refresh_projection_from_domain_state, thread_sensitive=True)(
            simulation_id=context.simulation_id,
            correlation_id=context.correlation_id,
        )
