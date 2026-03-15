from uuid import uuid4

from pydantic import ValidationError
import pytest

from apps.trainerlab.models import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    RespiratoryRate,
    TrainerSession,
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


def _initial_payload(
    *, etco2_key: str = "etco2", include_legacy_measurement_fields: bool = False
) -> dict:
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
        "conditions": [
            {
                "kind": "injury",
                "injury_category": "M",
                "injury_location": "HLA",
                "injury_kind": "LAC",
                "injury_description": "Scalp laceration",
            },
            {
                "kind": "illness",
                "name": "Heat illness",
                "description": "Heat stress signs present",
                "severity": "high",
            },
        ],
        "measurements": {
            "heart_rate": {
                **base_measurement,
                "min_value": 110,
                "max_value": 130,
            },
            "respiratory_rate": {
                **base_measurement,
                "min_value": 18,
                "max_value": 24,
            },
            "spo2": {**base_measurement, "min_value": 90, "max_value": 95},
            "blood_glucose_level": {
                **base_measurement,
                "min_value": 95,
                "max_value": 120,
            },
            "blood_pressure": {
                **base_measurement,
                "min_value": 110,
                "max_value": 130,
                "min_value_diastolic": 70,
                "max_value_diastolic": 90,
            },
        },
    }
    payload["measurements"][etco2_key] = {
        **base_measurement,
        "min_value": 30,
        "max_value": 40,
    }

    if include_legacy_measurement_fields:
        for measurement in payload["measurements"].values():
            measurement.update(
                {
                    "kind": "vital",
                    "key": "legacy_measurement",
                    "timestamp": 1_704_067_200,
                    "db_pk": 123,
                }
            )

    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestTrainerLabInitialPersistence:
    async def test_persists_conditions_and_nested_measurements(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        result = await persist_schema(schema, context)

        assert isinstance(result, Injury)
        assert await Injury.objects.filter(simulation_id=context.simulation_id).acount() == 1
        persisted_injury = await Injury.objects.filter(simulation_id=context.simulation_id).afirst()
        assert persisted_injury is not None
        assert persisted_injury.injury_category == "M"
        assert persisted_injury.injury_location == "HLA"
        assert persisted_injury.injury_kind == "LAC"
        assert await Illness.objects.filter(simulation_id=context.simulation_id).acount() == 1
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

    async def test_accepts_legacy_etc02_alias(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload(etco2_key="etc02"))

        await persist_schema(schema, context)

        assert await ETCO2.objects.filter(simulation_id=context.simulation_id).acount() == 1

    async def test_accepts_legacy_measurement_fields_and_discards_them(self, context):
        schema = InitialScenarioSchema.model_validate(
            _initial_payload(include_legacy_measurement_fields=True)
        )

        dumped = schema.model_dump(mode="json", by_alias=True)
        heart_rate = dumped["measurements"]["heart_rate"]
        assert "db_pk" not in heart_rate
        assert "timestamp" not in heart_rate
        assert "kind" not in heart_rate
        assert "key" not in heart_rate

    async def test_emits_outbox_events_for_sse(self, context):
        from apps.common.models import OutboxEvent

        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        condition_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="trainerlab.condition.created",
        )
        vital_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="trainerlab.vital.created",
        )

        assert await condition_events.acount() == 2
        assert await vital_events.acount() == 6

        example_vital = await vital_events.afirst()
        assert example_vital is not None
        assert example_vital.payload["origin"] == "initial_scenario"
        assert "vital_type" in example_vital.payload
        assert "domain_event_id" in example_vital.payload

    async def test_emits_outbox_events_when_context_call_id_is_uuid(self, simulation):
        from apps.common.models import OutboxEvent

        context = PersistContext(
            simulation_id=simulation.id,
            call_id=uuid4(),
        )
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        await persist_schema(schema, context)

        example_vital = await OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="trainerlab.vital.created",
        ).afirst()
        assert example_vital is not None
        assert example_vital.payload["call_id"] == str(context.call_id)

    async def test_accepts_friendly_injury_labels_and_normalizes_to_codes(self, context):
        payload = _initial_payload()
        payload["conditions"][0]["injury_category"] = "massive hemorrhage"
        payload["conditions"][0]["injury_location"] = "  left anterior head "
        payload["conditions"][0]["injury_kind"] = "laceration"

        schema = InitialScenarioSchema.model_validate(payload)
        await persist_schema(schema, context)

        injury = await Injury.objects.filter(simulation_id=context.simulation_id).afirst()
        assert injury is not None
        assert injury.injury_category == "M"
        assert injury.injury_location == "HLA"
        assert injury.injury_kind == "LAC"

    async def test_persists_scenario_brief_to_runtime_state_when_session_exists(
        self, simulation, context
    ):
        await TrainerSession.objects.acreate(
            simulation=simulation,
            status="seeded",
            runtime_state_json={},
        )
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        await persist_schema(schema, context)

        session = await TrainerSession.objects.aget(simulation=simulation)
        assert session.runtime_state_json["scenario_brief"]["read_aloud_brief"].startswith(
            "You are operating out of a roadside casualty collection point"
        )
        assert session.runtime_state_json["scenario_brief"]["evacuation_options"] == [
            "Ground evacuation",
            "Delayed rotary wing if weather clears",
        ]


def test_validates_base_vital_min_max_range():
    payload = _initial_payload()
    payload["measurements"]["heart_rate"]["min_value"] = 150
    payload["measurements"]["heart_rate"]["max_value"] = 120

    with pytest.raises(ValidationError):
        InitialScenarioSchema.model_validate(payload)


def test_initial_schema_uses_discriminated_condition_union():
    schema = InitialScenarioSchema.model_json_schema()
    condition_items = schema["properties"]["conditions"]["items"]

    assert "discriminator" in condition_items
    assert condition_items["discriminator"]["propertyName"] == "kind"


def test_validates_blood_pressure_logic():
    payload = _initial_payload()
    payload["measurements"]["blood_pressure"]["min_value_diastolic"] = 95
    payload["measurements"]["blood_pressure"]["max_value_diastolic"] = 80

    with pytest.raises(ValidationError):
        InitialScenarioSchema.model_validate(payload)


def test_measurement_schema_omits_legacy_fields():
    schema = InitialScenarioSchema.model_json_schema(by_alias=True)
    heart_rate_props = schema["$defs"]["HeartRate"]["properties"]

    assert "db_pk" not in heart_rate_props
    assert "timestamp" not in heart_rate_props
    assert "kind" not in heart_rate_props
    assert "key" not in heart_rate_props


def test_rejects_unknown_injury_labels():
    payload = _initial_payload()
    payload["conditions"][0]["injury_location"] = "unknown body part"

    with pytest.raises(ValidationError):
        InitialScenarioSchema.model_validate(payload)
