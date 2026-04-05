"""Tests for PulseAssessment: Pydantic schemas, Django model persistence, and runtime changes."""

from uuid import uuid4

from pydantic import ValidationError
import pytest

from apps.common.outbox.event_types import PATIENT_PULSE_CREATED, PATIENT_PULSE_UPDATED
from apps.trainerlab.orca.schemas.runtime import (
    RuntimePulseChange,
    RuntimeSnapshotPulse,
    RuntimeStateChanges,
    TrainerRuntimeSnapshot,
)
from apps.trainerlab.orca.schemas.types.pulse import PulseAssessmentItem
from orchestrai_django.persistence import PersistContext

# ---------------------------------------------------------------------------
# PulseAssessmentItem Pydantic schema
# ---------------------------------------------------------------------------


def _valid_pulse_item(location: str = "radial_left") -> dict:
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


class TestPulseAssessmentItemSchema:
    def test_valid_item_parses(self):
        item = PulseAssessmentItem.model_validate(_valid_pulse_item())
        assert item.location == "radial_left"
        assert item.present is True
        assert item.description == "strong"
        assert item.color_normal is True
        assert item.color_description == "pink"
        assert item.condition_normal is True
        assert item.condition_description == "dry"
        assert item.temperature_normal is True
        assert item.temperature_description == "warm"

    @pytest.mark.parametrize(
        "location",
        [
            "radial_left",
            "radial_right",
            "femoral_left",
            "femoral_right",
            "carotid_left",
            "carotid_right",
            "pedal_left",
            "pedal_right",
        ],
    )
    def test_all_valid_locations(self, location):
        item = PulseAssessmentItem.model_validate(_valid_pulse_item(location))
        assert item.location == location

    @pytest.mark.parametrize("description", ["strong", "bounding", "weak", "absent", "thready"])
    def test_all_valid_descriptions(self, description):
        data = {**_valid_pulse_item(), "description": description}
        item = PulseAssessmentItem.model_validate(data)
        assert item.description == description

    @pytest.mark.parametrize("color", ["pink", "pale", "mottled", "cyanotic", "flushed"])
    def test_all_valid_color_descriptions(self, color):
        data = {**_valid_pulse_item(), "color_description": color}
        item = PulseAssessmentItem.model_validate(data)
        assert item.color_description == color

    @pytest.mark.parametrize("condition", ["dry", "moist", "diaphoretic", "clammy"])
    def test_all_valid_condition_descriptions(self, condition):
        data = {**_valid_pulse_item(), "condition_description": condition}
        item = PulseAssessmentItem.model_validate(data)
        assert item.condition_description == condition

    @pytest.mark.parametrize("temperature", ["warm", "cool", "cold", "hot"])
    def test_all_valid_temperature_descriptions(self, temperature):
        data = {**_valid_pulse_item(), "temperature_description": temperature}
        item = PulseAssessmentItem.model_validate(data)
        assert item.temperature_description == temperature

    def test_invalid_location_rejected(self):
        data = {**_valid_pulse_item(), "location": "brachial_left"}
        with pytest.raises(ValidationError):
            PulseAssessmentItem.model_validate(data)

    def test_invalid_description_rejected(self):
        data = {**_valid_pulse_item(), "description": "normal"}
        with pytest.raises(ValidationError):
            PulseAssessmentItem.model_validate(data)

    def test_invalid_color_description_rejected(self):
        data = {**_valid_pulse_item(), "color_description": "yellow"}
        with pytest.raises(ValidationError):
            PulseAssessmentItem.model_validate(data)

    def test_invalid_condition_description_rejected(self):
        data = {**_valid_pulse_item(), "condition_description": "sweaty"}
        with pytest.raises(ValidationError):
            PulseAssessmentItem.model_validate(data)

    def test_invalid_temperature_description_rejected(self):
        data = {**_valid_pulse_item(), "temperature_description": "tepid"}
        with pytest.raises(ValidationError):
            PulseAssessmentItem.model_validate(data)

    def test_absent_pulse_with_weak_description(self):
        data = {
            **_valid_pulse_item(),
            "present": False,
            "description": "absent",
            "color_normal": False,
            "color_description": "cyanotic",
            "temperature_normal": False,
            "temperature_description": "cold",
        }
        item = PulseAssessmentItem.model_validate(data)
        assert item.present is False
        assert item.description == "absent"

    def test_orm_model_set(self):
        assert PulseAssessmentItem.__orm_model__ == "trainerlab.PulseAssessment"


# ---------------------------------------------------------------------------
# RuntimePulseChange schema
# ---------------------------------------------------------------------------


class TestRuntimePulseChangeSchema:
    def test_valid_pulse_change_parses(self):
        data = {
            "location": "femoral_right",
            "present": False,
            "description": "absent",
            "color_normal": False,
            "color_description": "pale",
            "condition_normal": False,
            "condition_description": "clammy",
            "temperature_normal": False,
            "temperature_description": "cold",
        }
        change = RuntimePulseChange.model_validate(data)
        assert change.location == "femoral_right"
        assert change.present is False
        assert change.action == "update"

    def test_action_defaults_to_update(self):
        data = {**_valid_pulse_item("radial_right")}
        change = RuntimePulseChange.model_validate(data)
        assert change.action == "update"

    def test_invalid_location_rejected(self):
        data = {**_valid_pulse_item(), "location": "invalid"}
        with pytest.raises(ValidationError):
            RuntimePulseChange.model_validate(data)


# ---------------------------------------------------------------------------
# RuntimeSnapshotPulse schema
# ---------------------------------------------------------------------------


class TestRuntimeSnapshotPulseSchema:
    def test_snapshot_pulse_parses(self):
        data = _valid_pulse_item("carotid_left")
        snap = RuntimeSnapshotPulse.model_validate(data)
        assert snap.location == "carotid_left"

    def test_no_action_field(self):
        assert not hasattr(RuntimeSnapshotPulse, "action") or "action" not in (
            RuntimeSnapshotPulse.model_fields
        )


# ---------------------------------------------------------------------------
# RuntimeStateChanges with pulses
# ---------------------------------------------------------------------------


class TestRuntimeStateChangesWithPulses:
    def test_default_empty_pulses(self):
        changes = RuntimeStateChanges()
        assert changes.pulses == []

    def test_state_changes_accepts_pulse_list(self):
        changes = RuntimeStateChanges.model_validate(
            {
                "pulses": [
                    {
                        "location": "radial_left",
                        "present": True,
                        "description": "strong",
                        "color_normal": True,
                        "color_description": "pink",
                        "condition_normal": True,
                        "condition_description": "dry",
                        "temperature_normal": True,
                        "temperature_description": "warm",
                    }
                ]
            }
        )
        assert len(changes.pulses) == 1
        assert changes.pulses[0].location == "radial_left"


# ---------------------------------------------------------------------------
# TrainerRuntimeSnapshot with pulses
# ---------------------------------------------------------------------------


class TestTrainerRuntimeSnapshotWithPulses:
    def test_snapshot_defaults_empty_pulses(self):
        snap = TrainerRuntimeSnapshot()
        assert snap.pulses == []

    def test_snapshot_accepts_pulse_list(self):
        snap = TrainerRuntimeSnapshot.model_validate(
            {
                "pulses": [
                    {
                        "location": "pedal_right",
                        "present": False,
                        "description": "absent",
                        "color_normal": False,
                        "color_description": "cyanotic",
                        "condition_normal": False,
                        "condition_description": "clammy",
                        "temperature_normal": False,
                        "temperature_description": "cold",
                    }
                ]
            }
        )
        assert len(snap.pulses) == 1
        assert snap.pulses[0].location == "pedal_right"


# ---------------------------------------------------------------------------
# PulseAssessment Django model persistence
# ---------------------------------------------------------------------------


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="PulseTest")


@pytest.fixture
def user(db, user_role):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=f"pulse_{uuid4().hex[:8]}@test.com",
        password="testpass",
        role=user_role,
    )


@pytest.fixture
def simulation(db, user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(user=user)


@pytest.fixture
def pulse_context(simulation):
    return PersistContext(
        simulation_id=simulation.id,
        call_id=str(uuid4()),
    )


def _full_initial_payload() -> dict:
    """Full payload with all required fields including pulses."""
    base_measurement = {"min_value": 10, "max_value": 20, "lock_value": False}
    pulse = {
        "location": "radial_left",
        "present": True,
        "description": "strong",
        "color_normal": True,
        "color_description": "pink",
        "condition_normal": True,
        "condition_description": "dry",
        "temperature_normal": True,
        "temperature_description": "warm",
    }
    return {
        "scenario_brief": {
            "read_aloud_brief": "Test scenario brief.",
            "environment": "Test",
            "location_overview": "Test location",
            "threat_context": "None",
            "evacuation_options": [],
            "evacuation_time": "10 minutes",
            "special_considerations": [],
        },
        "causes": [
            {
                "temp_id": "cause_test_laceration",
                "cause_kind": "injury",
                "kind": "laceration",
                "code": "LAC",
                "title": "Test laceration",
                "display_name": "Test laceration",
                "description": "Test laceration",
                "anatomical_location": "Left anterior head",
                "laterality": "left",
                "injury_location": "HLA",
                "injury_kind": "LAC",
                "injury_description": "Test laceration",
            }
        ],
        "problems": [
            {
                "temp_id": "problem_test_laceration",
                "kind": "open_wound",
                "code": "open_wound",
                "title": "Open wound",
                "display_name": "Open wound",
                "description": "Test laceration problem",
                "severity": "moderate",
                "march_category": "M",
                "cause_ref": "cause_test_laceration",
            }
        ],
        "recommended_interventions": [],
        "measurements": {
            "heart_rate": {**base_measurement, "min_value": 80, "max_value": 100},
            "respiratory_rate": {**base_measurement, "min_value": 14, "max_value": 20},
            "spo2": {**base_measurement, "min_value": 95, "max_value": 99},
            "blood_glucose_level": {**base_measurement, "min_value": 80, "max_value": 120},
            "blood_pressure": {
                **base_measurement,
                "min_value": 110,
                "max_value": 130,
                "min_value_diastolic": 70,
                "max_value_diastolic": 90,
            },
            "etco2": {**base_measurement, "min_value": 35, "max_value": 45},
        },
        "pulses": [
            pulse,
            {**pulse, "location": "radial_right"},
            {**pulse, "location": "femoral_left"},
            {**pulse, "location": "femoral_right"},
            {**pulse, "location": "carotid_left"},
            {**pulse, "location": "carotid_right"},
            {**pulse, "location": "pedal_left"},
            {**pulse, "location": "pedal_right"},
        ],
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPulseAssessmentPersistence:
    async def test_persists_pulse_assessments_to_db(self, pulse_context):
        from apps.trainerlab.models import PulseAssessment
        from apps.trainerlab.orca.schemas import InitialScenarioSchema
        from orchestrai_django.persistence import persist_schema

        schema = InitialScenarioSchema.model_validate(_full_initial_payload())
        await persist_schema(schema, pulse_context)

        count = await PulseAssessment.objects.filter(
            simulation_id=pulse_context.simulation_id
        ).acount()
        assert count == 8

    async def test_all_pulse_locations_persisted(self, pulse_context):
        from apps.trainerlab.models import PulseAssessment
        from apps.trainerlab.orca.schemas import InitialScenarioSchema
        from orchestrai_django.persistence import persist_schema

        schema = InitialScenarioSchema.model_validate(_full_initial_payload())
        await persist_schema(schema, pulse_context)

        locations = set()
        async for obj in PulseAssessment.objects.filter(simulation_id=pulse_context.simulation_id):
            locations.add(obj.location)

        expected = {
            "radial_left",
            "radial_right",
            "femoral_left",
            "femoral_right",
            "carotid_left",
            "carotid_right",
            "pedal_left",
            "pedal_right",
        }
        assert locations == expected

    async def test_pulse_fields_stored_correctly(self, pulse_context):
        from apps.trainerlab.models import PulseAssessment
        from apps.trainerlab.orca.schemas import InitialScenarioSchema
        from orchestrai_django.persistence import persist_schema

        schema = InitialScenarioSchema.model_validate(_full_initial_payload())
        await persist_schema(schema, pulse_context)

        obj = await PulseAssessment.objects.filter(
            simulation_id=pulse_context.simulation_id,
            location="radial_left",
        ).afirst()
        assert obj is not None
        assert obj.present is True
        assert obj.description == "strong"
        assert obj.color_normal is True
        assert obj.color_description == "pink"
        assert obj.condition_normal is True
        assert obj.condition_description == "dry"
        assert obj.temperature_normal is True
        assert obj.temperature_description == "warm"

    async def test_pulse_outbox_events_emitted(self, pulse_context):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.orca.schemas import InitialScenarioSchema
        from orchestrai_django.persistence import persist_schema

        schema = InitialScenarioSchema.model_validate(_full_initial_payload())
        await persist_schema(schema, pulse_context)

        pulse_events = OutboxEvent.objects.filter(
            simulation_id=pulse_context.simulation_id,
            event_type=PATIENT_PULSE_CREATED,
        )
        assert await pulse_events.acount() == 8

        event = await pulse_events.order_by("created_at").afirst()
        assert event is not None
        assert "location" in event.payload
        assert "domain_event_id" in event.payload
        assert event.payload["origin"] == "initial_scenario"


# ---------------------------------------------------------------------------
# _apply_pulse_change via apply_runtime_turn_output
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestApplyPulseChange:
    def test_apply_pulse_change_creates_record(self, simulation):
        from apps.trainerlab.models import PulseAssessment, TrainerSession
        from apps.trainerlab.services import _apply_pulse_change

        session = TrainerSession.objects.create(
            simulation=simulation,
            status="active",
            runtime_state_json={},
        )
        change = {
            "location": "radial_left",
            "present": True,
            "description": "weak",
            "color_normal": False,
            "color_description": "pale",
            "condition_normal": False,
            "condition_description": "clammy",
            "temperature_normal": False,
            "temperature_description": "cool",
        }
        _apply_pulse_change(session=session, change=change, correlation_id=None)

        obj = PulseAssessment.objects.filter(simulation=simulation, location="radial_left").first()
        assert obj is not None
        assert obj.present is True
        assert obj.description == "weak"
        assert obj.color_description == "pale"

    def test_apply_pulse_change_deactivates_previous(self, simulation):
        from apps.trainerlab.models import EventSource, PulseAssessment, TrainerSession
        from apps.trainerlab.services import _apply_pulse_change

        session = TrainerSession.objects.create(
            simulation=simulation,
            status="active",
            runtime_state_json={},
        )
        # Create initial assessment
        first = PulseAssessment.objects.create(
            simulation=simulation,
            source=EventSource.AI,
            location="radial_left",
            present=True,
            description="strong",
            color_normal=True,
            color_description="pink",
            condition_normal=True,
            condition_description="dry",
            temperature_normal=True,
            temperature_description="warm",
        )
        assert first.is_active is True

        change = {
            "location": "radial_left",
            "present": False,
            "description": "absent",
            "color_normal": False,
            "color_description": "cyanotic",
            "condition_normal": False,
            "condition_description": "clammy",
            "temperature_normal": False,
            "temperature_description": "cold",
        }
        _apply_pulse_change(session=session, change=change, correlation_id=None)

        first.refresh_from_db()
        assert first.is_active is False

        active = PulseAssessment.objects.filter(
            simulation=simulation, location="radial_left", is_active=True
        ).first()
        assert active is not None
        assert active.description == "absent"

    def test_apply_pulse_change_emits_outbox_event(self, simulation):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import TrainerSession
        from apps.trainerlab.services import _apply_pulse_change

        session = TrainerSession.objects.create(
            simulation=simulation,
            status="active",
            runtime_state_json={},
        )
        change = {
            "location": "femoral_left",
            "present": True,
            "description": "weak",
            "color_normal": False,
            "color_description": "pale",
            "condition_normal": True,
            "condition_description": "dry",
            "temperature_normal": False,
            "temperature_description": "cool",
        }
        _apply_pulse_change(session=session, change=change, correlation_id="test-corr-id")

        event = OutboxEvent.objects.filter(
            simulation_id=simulation.id,
            event_type=PATIENT_PULSE_UPDATED,
        ).first()
        assert event is not None
        assert event.payload["location"] == "femoral_left"
        assert event.payload["action"] == "updated"

    def test_apply_pulse_change_ignores_missing_location(self, simulation):
        from apps.trainerlab.models import PulseAssessment, TrainerSession
        from apps.trainerlab.services import _apply_pulse_change

        session = TrainerSession.objects.create(
            simulation=simulation,
            status="active",
            runtime_state_json={},
        )
        _apply_pulse_change(session=session, change={}, correlation_id=None)

        assert PulseAssessment.objects.filter(simulation=simulation).count() == 0


# ---------------------------------------------------------------------------
# event_payloads serialization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSerializePulseEvent:
    def test_serialize_pulse_assessment_event(self, simulation):
        from apps.trainerlab.event_payloads import serialize_domain_event
        from apps.trainerlab.models import EventSource, PulseAssessment

        obj = PulseAssessment.objects.create(
            simulation=simulation,
            source=EventSource.AI,
            location="carotid_right",
            present=True,
            description="bounding",
            color_normal=True,
            color_description="flushed",
            condition_normal=False,
            condition_description="diaphoretic",
            temperature_normal=True,
            temperature_description="hot",
        )
        payload = serialize_domain_event(obj)

        assert payload["event_kind"] == "pulse_assessment"
        assert payload["vital_type"] == "pulse_assessment"
        assert payload["location"] == "carotid_right"
        assert payload["present"] is True
        assert payload["description"] == "bounding"
        assert payload["color_normal"] is True
        assert payload["color_description"] == "flushed"
        assert payload["condition_normal"] is False
        assert payload["condition_description"] == "diaphoretic"
        assert payload["temperature_normal"] is True
        assert payload["temperature_description"] == "hot"
        assert payload["domain_event_id"] == obj.id
        assert payload["simulation_id"] == simulation.id


# ---------------------------------------------------------------------------
# ScenarioSnapshot includes pulses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScenarioSnapshotPulses:
    def test_snapshot_includes_pulses(self, simulation):
        from apps.trainerlab.models import EventSource, PulseAssessment, TrainerSession
        from apps.trainerlab.viewmodels import (
            build_scenario_snapshot,
            load_trainer_engine_aggregate,
        )

        session = TrainerSession.objects.create(
            simulation=simulation,
            status="active",
            runtime_state_json={},
        )
        PulseAssessment.objects.create(
            simulation=simulation,
            source=EventSource.AI,
            location="radial_left",
            present=True,
            description="strong",
            color_normal=True,
            color_description="pink",
            condition_normal=True,
            condition_description="dry",
            temperature_normal=True,
            temperature_description="warm",
        )

        snapshot = build_scenario_snapshot(
            load_trainer_engine_aggregate(session=session)
        ).model_dump(mode="json")
        assert "pulses" in snapshot
        assert len(snapshot["pulses"]) == 1
        assert snapshot["pulses"][0]["location"] == "radial_left"
        assert snapshot["pulses"][0]["vital_type"] == "pulse_assessment"

    def test_snapshot_empty_pulses_when_none(self, simulation):
        from apps.trainerlab.models import TrainerSession
        from apps.trainerlab.viewmodels import (
            build_scenario_snapshot,
            load_trainer_engine_aggregate,
        )

        session = TrainerSession.objects.create(
            simulation=simulation,
            status="active",
            runtime_state_json={},
        )
        snapshot = build_scenario_snapshot(
            load_trainer_engine_aggregate(session=session)
        ).model_dump(mode="json")
        assert snapshot["pulses"] == []
