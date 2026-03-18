from uuid import uuid4

from pydantic import ValidationError
import pytest

from apps.trainerlab.models import (
    ETCO2,
    SPO2,
    AssessmentFinding,
    BloodGlucoseLevel,
    BloodPressure,
    DiagnosticResult,
    DispositionState,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    Problem,
    PulseAssessment,
    RecommendationEvaluation,
    RecommendedIntervention,
    ResourceState,
    RespiratoryRate,
    ScenarioBrief,
)
from apps.trainerlab.orca.schemas import InitialScenarioSchema
from orchestrai_django.persistence import PersistContext, persist_schema


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="TrainerLab Persist")


@pytest.fixture
def user(db, user_role):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=f"trainerlab_{uuid4().hex[:8]}@test.com",
        password="testpass123",
        role=user_role,
    )


@pytest.fixture
def simulation(db, user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(user=user)


@pytest.fixture
def context(simulation):
    return PersistContext(
        simulation_id=simulation.id,
        call_id=str(uuid4()),
    )


def _pulse_item(location: str) -> dict:
    return {
        "location": location,
        "present": True,
        "description": "strong",
        "color_normal": True,
        "color_description": "pink",
        "condition_normal": True,
        "condition_description": "dry",
        "temperature_normal": True,
        "temperature_description": "warm",
    }


def _initial_payload(*, include_performed: bool = False) -> dict:
    base_measurement = {
        "min_value": 10,
        "max_value": 20,
        "lock_value": False,
    }
    payload = {
        "scenario_brief": {
            "read_aloud_brief": (
                "You are operating out of a roadside casualty collection point on the edge of a "
                "small village. Sporadic hostile fire has been reported nearby. Ground evacuation "
                "is available in about 20 minutes."
            ),
            "environment": "Roadside casualty collection point with limited cover",
            "location_overview": "Edge of a small village along a dusty supply route",
            "threat_context": "Sporadic hostile fire reported within the surrounding area",
            "evacuation_options": ["Ground evacuation", "Delayed rotary wing if weather clears"],
            "evacuation_time": "Approximately 20 minutes by ground",
            "special_considerations": ["Limited light", "Dust may affect visibility"],
        },
        "causes": [
            {
                "temp_id": "cause_gsw_left_thigh",
                "cause_kind": "injury",
                "kind": "gunshot_wound",
                "code": "GSW",
                "title": "GSW left thigh",
                "display_name": "GSW left thigh",
                "description": "Penetrating gunshot wound to the left thigh",
                "anatomical_location": "Left thigh",
                "laterality": "left",
                "injury_location": "LUL",
                "injury_kind": "GSW",
                "injury_description": "GSW left thigh",
            },
            {
                "temp_id": "cause_infection",
                "cause_kind": "illness",
                "kind": "infection",
                "code": "INFECTION",
                "title": "Bacterial infection",
                "display_name": "Bacterial infection",
                "name": "Bacterial infection",
                "description": "Febrile infectious illness with dehydration",
            },
        ],
        "problems": [
            {
                "temp_id": "problem_hemorrhage",
                "kind": "hemorrhage",
                "code": "hemorrhage",
                "title": "Massive hemorrhage from left thigh",
                "display_name": "Massive hemorrhage from left thigh",
                "description": "Ongoing life-threatening extremity bleeding",
                "severity": "critical",
                "march_category": "M",
                "anatomical_location": "Left thigh",
                "laterality": "left",
                "cause_ref": "cause_gsw_left_thigh",
                "recommendation_refs": ["rec_tq"],
            },
            {
                "temp_id": "problem_open_wound",
                "kind": "open_wound",
                "code": "open_wound",
                "title": "Open wound left thigh",
                "display_name": "Open wound left thigh",
                "description": "Penetrating soft tissue wound",
                "severity": "high",
                "march_category": "M",
                "anatomical_location": "Left thigh",
                "laterality": "left",
                "cause_ref": "cause_gsw_left_thigh",
                "recommendation_refs": ["rec_pressure"],
            },
            {
                "temp_id": "problem_infection",
                "kind": "infectious_process",
                "code": "infectious_process",
                "title": "Infectious process",
                "display_name": "Infectious process",
                "description": "Likely bacterial infection",
                "severity": "high",
                "march_category": "C",
                "cause_ref": "cause_infection",
                "recommendation_refs": ["rec_antibiotics"],
            },
            {
                "temp_id": "problem_dehydration",
                "kind": "dehydration",
                "code": "dehydration",
                "title": "Dehydration",
                "display_name": "Dehydration",
                "description": "Volume depletion from illness",
                "severity": "moderate",
                "march_category": "C",
                "cause_ref": "cause_infection",
                "recommendation_refs": ["rec_invalid"],
            },
        ],
        "recommended_interventions": [
            {
                "temp_id": "rec_tq",
                "intervention_kind": "tourniquet",
                "title": "Tourniquet to left thigh",
                "target_problem_ref": "problem_hemorrhage",
                "target_cause_ref": "cause_gsw_left_thigh",
                "rationale": "Extremity hemorrhage control",
                "priority": 1,
                "site": "left_leg",
            },
            {
                "temp_id": "rec_pressure",
                "intervention_kind": "pressure dressing",
                "title": "Pressure dressing to left thigh",
                "target_problem_ref": "problem_open_wound",
                "target_cause_ref": "cause_gsw_left_thigh",
                "rationale": "Cover and protect the wound",
                "priority": 2,
                "site": "left_leg",
            },
            {
                "temp_id": "rec_antibiotics",
                "intervention_kind": "antibiotics",
                "title": "Antibiotics for infection",
                "target_problem_ref": "problem_infection",
                "target_cause_ref": "cause_infection",
                "rationale": "Treat infectious process",
                "priority": 2,
                "site": "systemic",
            },
            {
                "temp_id": "rec_invalid",
                "intervention_kind": "magic healing beam",
                "title": "Made up care",
                "target_problem_ref": "problem_dehydration",
                "target_cause_ref": "cause_infection",
                "rationale": "Should be rejected by deterministic validation",
            },
        ],
        "assessment_findings": [
            {
                "temp_id": "finding_bleeding",
                "finding_kind": "active_bleeding",
                "title": "Active bleeding",
                "description": "Bright red bleeding continues from the left thigh wound.",
                "status": "present",
                "severity": "critical",
                "target_problem_ref": "problem_hemorrhage",
                "anatomical_location": "Left thigh",
                "laterality": "left",
            }
        ],
        "diagnostic_results": [
            {
                "temp_id": "diag_lactate",
                "diagnostic_kind": "lactate",
                "title": "Lactate pending",
                "status": "pending",
                "value_text": "",
                "target_problem_ref": "problem_infection",
            }
        ],
        "resources": [
            {
                "temp_id": "resource_binder",
                "resource_kind": "pelvic_binder",
                "title": "Pelvic binder",
                "status": "available",
                "quantity_available": 1,
                "quantity_unit": "device",
            }
        ],
        "disposition": {
            "status": "hold",
            "transport_mode": "ground",
            "destination": "Role 2",
            "eta_minutes": 20,
            "handoff_ready": False,
            "scene_constraints": ["sporadic hostile fire"],
        },
        "measurements": {
            "heart_rate": {**base_measurement, "min_value": 110, "max_value": 130},
            "respiratory_rate": {**base_measurement, "min_value": 18, "max_value": 24},
            "spo2": {**base_measurement, "min_value": 90, "max_value": 95},
            "blood_glucose_level": {**base_measurement, "min_value": 95, "max_value": 120},
            "blood_pressure": {
                **base_measurement,
                "min_value": 110,
                "max_value": 130,
                "min_value_diastolic": 70,
                "max_value_diastolic": 90,
            },
            "etco2": {**base_measurement, "min_value": 30, "max_value": 40},
        },
        "pulses": [
            _pulse_item("radial_left"),
            _pulse_item("radial_right"),
            _pulse_item("femoral_left"),
            _pulse_item("femoral_right"),
            _pulse_item("carotid_left"),
            _pulse_item("carotid_right"),
            _pulse_item("pedal_left"),
            _pulse_item("pedal_right"),
        ],
    }
    if include_performed:
        payload["performed_interventions"] = [
            {
                "intervention_kind": "tourniquet",
                "target_problem_ref": "problem_hemorrhage",
                "site": "left_leg",
                "notes": "Trusted seeded intervention",
                "details": {"kind": "tourniquet", "version": 1, "application_mode": "deliberate"},
                "initiated_by_type": "system",
            }
        ]
    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestTrainerLabInitialPersistence:
    async def test_persists_explicit_causes_problems_recommendations_and_measurements(
        self, context
    ):
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        result = await persist_schema(schema, context)

        assert isinstance(result, dict)
        assert await Injury.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert await Illness.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert await Problem.objects.filter(simulation_id=context.simulation_id).acount() == 4
        assert (
            await RecommendedIntervention.objects.filter(
                simulation_id=context.simulation_id
            ).acount()
            == 3
        )
        assert (
            await RecommendationEvaluation.objects.filter(
                simulation_id=context.simulation_id
            ).acount()
            == 4
        )
        assert await Intervention.objects.filter(simulation_id=context.simulation_id).acount() == 0
        assert await HeartRate.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert (
            await RespiratoryRate.objects.filter(simulation_id=context.simulation_id).acount() == 1
        )
        assert await SPO2.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert await ETCO2.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert (
            await BloodGlucoseLevel.objects.filter(simulation_id=context.simulation_id).acount()
            == 1
        )
        assert await BloodPressure.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert (
            await PulseAssessment.objects.filter(simulation_id=context.simulation_id).acount() == 8
        )
        assert (
            await RecommendationEvaluation.objects.filter(
                simulation_id=context.simulation_id,
                validation_status="rejected",
            ).acount()
            == 1
        )

    async def test_one_cause_can_create_multiple_problems_for_injury_and_illness(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        injury = await Injury.objects.filter(simulation_id=context.simulation_id).afirst()
        illness = await Illness.objects.filter(simulation_id=context.simulation_id).afirst()
        assert injury is not None
        assert illness is not None

        assert await Problem.objects.filter(cause_injury=injury).acount() == 2
        assert await Problem.objects.filter(cause_illness=illness).acount() == 2

    async def test_problem_payloads_include_direct_cause_and_status(self, context):
        from apps.common.models import OutboxEvent

        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        problem_event = (
            await OutboxEvent.objects.filter(
                simulation_id=context.simulation_id,
                event_type="problem.created",
            )
            .order_by("created_at", "id")
            .afirst()
        )
        assert problem_event is not None
        assert problem_event.payload["problem_id"]
        assert problem_event.payload["cause_id"]
        assert problem_event.payload["cause_kind"] in {"injury", "illness"}
        assert problem_event.payload["status"] == "active"
        assert "treated_at" in problem_event.payload
        assert "controlled_at" in problem_event.payload
        assert "resolved_at" in problem_event.payload

    async def test_recommendation_payloads_are_distinct_and_include_provenance(self, context):
        from apps.common.models import OutboxEvent

        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        recommendation_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="recommended_intervention.created",
        ).order_by("created_at", "id")
        assert await recommendation_events.acount() == 3

        event = await recommendation_events.afirst()
        assert event is not None
        assert event.payload["recommendation_id"]
        assert event.payload["target_problem_id"]
        assert event.payload["recommendation_source"] in {"ai", "merged"}
        assert event.payload["validation_status"] in {"accepted", "normalized"}
        assert "intervention_id" not in event.payload

        evaluation_event = (
            await OutboxEvent.objects.filter(
                simulation_id=context.simulation_id,
                event_type="trainerlab.recommendation_evaluation.created",
            )
            .order_by("created_at", "id")
            .afirst()
        )
        assert evaluation_event is not None
        assert evaluation_event.payload["validation_status"] in {
            "accepted",
            "normalized",
            "rejected",
        }
        assert "target_problem_id" in evaluation_event.payload

    async def test_invalid_recommendation_is_rejected_and_free_text_is_normalized(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        rejected = await RecommendedIntervention.objects.filter(
            simulation_id=context.simulation_id,
            title="Made up care",
        ).aexists()
        assert rejected is False

        normalized = await RecommendedIntervention.objects.filter(
            simulation_id=context.simulation_id,
            target_problem__title="Open wound left thigh",
        ).afirst()
        assert normalized is not None
        assert normalized.kind == "pressure_dressing"
        assert normalized.validation_status == RecommendedIntervention.ValidationStatus.NORMALIZED

    async def test_normal_ai_seeding_rejects_performed_interventions(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload(include_performed=True))

        with pytest.raises(ValueError, match="may not create performed interventions"):
            await persist_schema(schema, context)

        assert await Intervention.objects.filter(simulation_id=context.simulation_id).acount() == 0

    async def test_trusted_seeded_performed_intervention_creates_actual_intervention_and_adjudicates(
        self, simulation
    ):
        context = PersistContext(
            simulation_id=simulation.id,
            call_id=str(uuid4()),
            extra={"allow_seeded_performed_interventions": True},
        )
        schema = InitialScenarioSchema.model_validate(_initial_payload(include_performed=True))

        await persist_schema(schema, context)

        assert await Intervention.objects.filter(simulation_id=simulation.id).acount() == 1
        hemorrhage = await Problem.objects.filter(
            simulation_id=simulation.id,
            kind="hemorrhage",
        ).afirst()
        open_wound = await Problem.objects.filter(
            simulation_id=simulation.id,
            kind="open_wound",
        ).afirst()
        assert hemorrhage is not None
        assert open_wound is not None
        assert hemorrhage.status == Problem.Status.CONTROLLED
        assert open_wound.status == Problem.Status.ACTIVE

    async def test_scenario_brief_and_vitals_persist(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        brief = await ScenarioBrief.objects.filter(simulation_id=context.simulation_id).afirst()
        assert brief is not None
        assert brief.read_aloud_brief.startswith(
            "You are operating out of a roadside casualty collection point"
        )
        assert brief.evacuation_options == [
            "Ground evacuation",
            "Delayed rotary wing if weather clears",
        ]

    async def test_initial_seed_supports_findings_diagnostics_resources_and_disposition(
        self, context
    ):
        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        assert (
            await AssessmentFinding.objects.filter(simulation_id=context.simulation_id).acount()
            == 1
        )
        assert (
            await DiagnosticResult.objects.filter(simulation_id=context.simulation_id).acount() == 1
        )
        assert await ResourceState.objects.filter(simulation_id=context.simulation_id).acount() == 1
        assert (
            await DispositionState.objects.filter(simulation_id=context.simulation_id).acount() == 1
        )


def test_initial_schema_uses_discriminated_cause_union():
    schema = InitialScenarioSchema.model_json_schema()
    cause_items = schema["properties"]["causes"]["items"]

    assert "discriminator" in cause_items
    assert cause_items["discriminator"]["propertyName"] == "cause_kind"


def test_validates_blood_pressure_logic():
    payload = _initial_payload()
    payload["measurements"]["blood_pressure"]["min_value_diastolic"] = 95
    payload["measurements"]["blood_pressure"]["max_value_diastolic"] = 80

    with pytest.raises(ValidationError):
        InitialScenarioSchema.model_validate(payload)


def test_rejects_unknown_problem_references():
    payload = _initial_payload()
    payload["recommended_interventions"][0]["target_problem_ref"] = "missing_problem"

    with pytest.raises(ValidationError):
        InitialScenarioSchema.model_validate(payload)
