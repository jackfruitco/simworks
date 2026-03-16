from uuid import uuid4

from pydantic import ValidationError
import pytest

from apps.trainerlab.models import (
    ETCO2,
    SPO2,
    ABCEvent,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    PulseAssessment,
    RespiratoryRate,
    ScenarioBrief,
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
    payload["pulses"] = [
        _pulse_item("radial_left"),
        _pulse_item("radial_right"),
        _pulse_item("femoral_left"),
        _pulse_item("femoral_right"),
        _pulse_item("carotid_left"),
        _pulse_item("carotid_right"),
        _pulse_item("pedal_left"),
        _pulse_item("pedal_right"),
    ]

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

    async def test_persists_pulse_assessments(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        await persist_schema(schema, context)

        assert (
            await PulseAssessment.objects.filter(simulation_id=context.simulation_id).acount() == 8
        )
        radial_left = await PulseAssessment.objects.filter(
            simulation_id=context.simulation_id,
            location="radial_left",
        ).afirst()
        assert radial_left is not None
        assert radial_left.present is True
        assert radial_left.description == "strong"
        assert radial_left.color_normal is True
        assert radial_left.color_description == "pink"
        assert radial_left.condition_normal is True
        assert radial_left.condition_description == "dry"
        assert radial_left.temperature_normal is True
        assert radial_left.temperature_description == "warm"

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
        pulse_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="trainerlab.pulse.created",
        )

        assert await condition_events.acount() == 2
        assert await vital_events.acount() == 6
        assert await pulse_events.acount() == 8

        example_vital = await vital_events.afirst()
        assert example_vital is not None
        assert example_vital.payload["origin"] == "initial_scenario"
        assert "vital_type" in example_vital.payload
        assert "domain_event_id" in example_vital.payload

        example_pulse = await pulse_events.afirst()
        assert example_pulse is not None
        assert example_pulse.payload["origin"] == "initial_scenario"
        assert "location" in example_pulse.payload
        assert "domain_event_id" in example_pulse.payload

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

    async def test_scenario_brief_persisted_as_abc_event(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        await persist_schema(schema, context)

        brief = await ScenarioBrief.objects.filter(simulation_id=context.simulation_id).afirst()
        assert brief is not None
        assert brief.read_aloud_brief.startswith(
            "You are operating out of a roadside casualty collection point"
        )
        assert brief.environment == "Roadside casualty collection point with limited cover"
        assert brief.location_overview == "Edge of a small village along a dusty supply route"
        assert brief.threat_context == "Sporadic hostile fire reported within the surrounding area"
        # Verify JSONField lists are stored as real lists, not stringified
        assert brief.evacuation_options == [
            "Ground evacuation",
            "Delayed rotary wing if weather clears",
        ]
        assert isinstance(brief.evacuation_options, list)
        assert brief.evacuation_time == "Approximately 20 minutes by ground"
        assert brief.special_considerations == ["Limited light", "Dust may affect visibility"]
        assert isinstance(brief.special_considerations, list)
        assert brief.is_active is True

    async def test_scenario_brief_appears_in_abc_event_timeline(self, context):
        schema = InitialScenarioSchema.model_validate(_initial_payload())

        await persist_schema(schema, context)

        events = ABCEvent.objects.filter(simulation_id=context.simulation_id)
        event_types = set()
        async for event in events:
            event_types.add(type(event).__name__)
        assert "ScenarioBrief" in event_types

    async def test_scenario_brief_sse_outbox_event(self, context):
        from apps.common.models import OutboxEvent

        schema = InitialScenarioSchema.model_validate(_initial_payload())
        await persist_schema(schema, context)

        brief_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="trainerlab.scenario_brief.created",
        )
        assert await brief_events.acount() == 1
        event = await brief_events.afirst()
        assert event is not None
        assert event.payload["read_aloud_brief"].startswith(
            "You are operating out of a roadside casualty collection point"
        )
        assert event.payload["domain_event_type"] == "ScenarioBrief"
        assert event.payload["origin"] == "initial_scenario"

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

    async def test_scenario_brief_superseding(self, context):
        """Second brief with supersedes_event deactivates the first."""
        from apps.simcore.models import Simulation

        simulation = await Simulation.objects.aget(id=context.simulation_id)

        first = await ScenarioBrief.objects.acreate(
            simulation=simulation,
            read_aloud_brief="First brief",
            is_active=True,
        )
        second = await ScenarioBrief.objects.acreate(
            simulation=simulation,
            read_aloud_brief="Second brief",
            supersedes_event=first,
            is_active=True,
        )
        first.is_active = False
        await first.asave(update_fields=["is_active"])

        active_briefs = ScenarioBrief.objects.filter(
            simulation=simulation,
            is_active=True,
        )
        assert await active_briefs.acount() == 1
        active = await active_briefs.afirst()
        assert active.id == second.id
        assert active.read_aloud_brief == "Second brief"


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
