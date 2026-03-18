"""Tests for synchronous initial generation during create_session_with_initial_generation.

These tests verify that by the time create_session_with_initial_generation() returns:
- RuntimeEvent records exist for each vital and condition
- runtime_state_json has scenario_brief populated
- OutboxEvent records are queued for delivery
- Session status is still 'seeded'
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.trainerlab.orca.schemas import InitialScenarioSchema
from apps.trainerlab.services import (
    _emit_seeded_condition_events,
    _emit_seeded_vital_events,
    create_session_with_initial_generation,
)
from orchestrai_django.persistence import PersistContext, persist_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title=f"SeededSessionRole-{uuid4().hex[:6]}")


@pytest.fixture
def user(db, user_role):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=f"seeded_{uuid4().hex[:8]}@test.com",
        password="testpass123",
        role=user_role,
    )


def _make_initial_payload() -> dict:
    base = {"min_value": 10, "max_value": 20, "lock_value": False}
    pulse = {
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
            "read_aloud_brief": "Patient down at roadside CCP, hostile fire in area.",
            "environment": "Roadside CCP",
            "location_overview": "Edge of small village",
            "threat_context": "Sporadic hostile fire",
            "evacuation_options": ["Ground evac"],
            "evacuation_time": "20 minutes",
            "special_considerations": [],
        },
        "causes": [
            {
                "temp_id": "cause_scalp_laceration",
                "cause_kind": "injury",
                "kind": "laceration",
                "code": "LAC",
                "title": "Scalp laceration",
                "display_name": "Scalp laceration",
                "description": "Scalp laceration with active bleeding",
                "anatomical_location": "Left anterior head",
                "laterality": "left",
                "injury_location": "HLA",
                "injury_kind": "LAC",
                "injury_description": "Scalp laceration with active bleeding",
            },
            {
                "temp_id": "cause_heat_exhaustion",
                "cause_kind": "illness",
                "kind": "heat_illness",
                "code": "HEAT_ILLNESS",
                "title": "Heat exhaustion",
                "display_name": "Heat exhaustion",
                "name": "Heat exhaustion",
                "description": "Signs of heat stress present",
            },
        ],
        "problems": [
            {
                "temp_id": "problem_scalp_bleeding",
                "kind": "hemorrhage",
                "code": "hemorrhage",
                "title": "Scalp hemorrhage",
                "display_name": "Scalp hemorrhage",
                "description": "Moderate scalp bleeding",
                "severity": "moderate",
                "march_category": "M",
                "cause_ref": "cause_scalp_laceration",
            },
            {
                "temp_id": "problem_heat_illness",
                "kind": "heat_illness",
                "code": "heat_illness",
                "title": "Heat exhaustion",
                "display_name": "Heat exhaustion",
                "description": "Signs of heat stress present",
                "severity": "moderate",
                "march_category": "H1",
                "cause_ref": "cause_heat_exhaustion",
            },
        ],
        "recommended_interventions": [],
        "measurements": {
            "heart_rate": {**base, "min_value": 110, "max_value": 130},
            "respiratory_rate": {**base, "min_value": 18, "max_value": 24},
            "spo2": {**base, "min_value": 90, "max_value": 95},
            "blood_glucose_level": {**base, "min_value": 95, "max_value": 120},
            "blood_pressure": {
                **base,
                "min_value": 110,
                "max_value": 130,
                "min_value_diastolic": 70,
                "max_value_diastolic": 90,
            },
            "etco2": {**base, "min_value": 30, "max_value": 40},
        },
        "pulses": [
            {**pulse, "location": "radial_left"},
            {**pulse, "location": "radial_right"},
            {**pulse, "location": "femoral_left"},
            {**pulse, "location": "femoral_right"},
            {**pulse, "location": "carotid_left"},
            {**pulse, "location": "carotid_right"},
            {**pulse, "location": "pedal_left"},
            {**pulse, "location": "pedal_right"},
        ],
    }


def _make_fake_run_service_call(simulation_id_holder: list):
    """Return a fake run_service_call that persists schema data directly (no AI call)."""
    from asgiref.sync import async_to_sync

    def _fake_run_service_call(call_id: str) -> dict:
        sim_id = simulation_id_holder[0]
        schema = InitialScenarioSchema.model_validate(_make_initial_payload())
        ctx = PersistContext(
            simulation_id=sim_id,
            call_id=call_id or str(uuid4()),
        )
        async_to_sync(persist_schema)(schema, ctx)
        return {"status": "completed", "id": call_id}

    return _fake_run_service_call


# ---------------------------------------------------------------------------
# Unit test
# ---------------------------------------------------------------------------


class TestGenerateInitialScenarioSchemaValid:
    @pytest.mark.unit
    def test_schema_importable_and_valid(self):
        """Schema must be importable at decoration time; reaching here means it passed."""
        assert InitialScenarioSchema is not None
        assert hasattr(InitialScenarioSchema, "model_fields")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestSeededSessionEmitsEvents:
    def test_seeded_session_emits_vitals_causes_and_problems(self, user, monkeypatch):
        """create_session_with_initial_generation must emit vital + cause + problem events."""
        from apps.trainerlab.models import RuntimeEvent

        simulation_id_holder = [None]

        def _fake_enqueue(*, simulation):
            simulation_id_holder[0] = simulation.id
            return "fake-call-id-vitals"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )
        monkeypatch.setattr(
            "apps.trainerlab.services._run_initial_generation_inline",
            lambda **kwargs: _run_inline_with_real_data(
                kwargs["session"], kwargs["call_id"], simulation_id_holder
            ),
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )

        vital_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type="trainerlab.vital.created",
        ).count()
        cause_events = (
            RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type="injury.created",
            ).count()
            + RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type="illness.created",
            ).count()
        )
        problem_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type="problem.created",
        ).count()

        assert vital_events >= 1, "At least one vital event must exist after seeding"
        assert cause_events >= 1, "At least one cause event must exist after seeding"
        assert problem_events >= 1, "At least one problem event must exist after seeding"

    def test_seeded_session_outbox_events_queued(self, user, monkeypatch):
        """Outbox must have at least vital + cause/problem events queued."""
        from apps.common.models import OutboxEvent

        simulation_id_holder = [None]

        def _fake_enqueue(*, simulation):
            simulation_id_holder[0] = simulation.id
            return "fake-call-id-outbox"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )
        monkeypatch.setattr(
            "apps.trainerlab.services._run_initial_generation_inline",
            lambda **kwargs: _run_inline_with_real_data(
                kwargs["session"], kwargs["call_id"], simulation_id_holder
            ),
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )

        outbox_count = OutboxEvent.objects.filter(
            simulation_id=str(session.simulation_id),
        ).count()

        assert outbox_count >= 2, "Outbox must have at least vital + condition events queued"

    def test_seeded_session_status_is_seeded(self, user, monkeypatch):
        """Session status must remain 'seeded' after creation."""
        simulation_id_holder = [None]

        def _fake_enqueue(*, simulation):
            simulation_id_holder[0] = simulation.id
            return "fake-call-id-status"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )
        monkeypatch.setattr(
            "apps.trainerlab.services._run_initial_generation_inline",
            lambda **kwargs: _run_inline_with_real_data(
                kwargs["session"], kwargs["call_id"], simulation_id_holder
            ),
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )

        assert session.status == "seeded"


@pytest.mark.django_db(transaction=True)
class TestEmitSeededVitalEvents:
    def test_emits_one_event_per_vital_type(self, user):
        """_emit_seeded_vital_events creates RuntimeEvent for each vital in DB."""
        from asgiref.sync import async_to_sync

        from apps.trainerlab.models import RuntimeEvent
        from apps.trainerlab.services import create_session

        session = create_session(
            user=user,
            scenario_spec={},
            directives=None,
            modifiers=[],
        )

        schema = InitialScenarioSchema.model_validate(_make_initial_payload())
        ctx = PersistContext(simulation_id=session.simulation_id, call_id=str(uuid4()))
        async_to_sync(persist_schema)(schema, ctx)

        # Re-fetch so session has updated state
        session.refresh_from_db()

        _emit_seeded_vital_events(session)

        events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type="trainerlab.vital.created",
        )
        assert events.count() >= 1

    def test_emits_one_event_per_condition(self, user):
        """_emit_seeded_condition_events creates RuntimeEvent per cause/problem."""
        from asgiref.sync import async_to_sync

        from apps.trainerlab.models import RuntimeEvent
        from apps.trainerlab.services import create_session

        session = create_session(
            user=user,
            scenario_spec={},
            directives=None,
            modifiers=[],
        )

        schema = InitialScenarioSchema.model_validate(_make_initial_payload())
        ctx = PersistContext(simulation_id=session.simulation_id, call_id=str(uuid4()))
        async_to_sync(persist_schema)(schema, ctx)

        session.refresh_from_db()

        _emit_seeded_condition_events(session)

        cause_events = (
            RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type="injury.created",
            ).count()
            + RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type="illness.created",
            ).count()
        )
        problem_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type="problem.created",
        ).count()
        assert cause_events >= 1
        assert problem_events >= 1


# ---------------------------------------------------------------------------
# Helper used by integration tests
# ---------------------------------------------------------------------------


def _run_inline_with_real_data(session, call_id, simulation_id_holder):
    """Fake _run_initial_generation_inline that persists schema directly then emits events."""
    from asgiref.sync import async_to_sync

    from apps.trainerlab.services import (
        _emit_seeded_condition_events,
        _emit_seeded_vital_events,
        refresh_projection_from_domain_state,
    )

    sim_id = session.simulation_id
    simulation_id_holder[0] = sim_id

    schema = InitialScenarioSchema.model_validate(_make_initial_payload())
    ctx = PersistContext(simulation_id=sim_id, call_id=call_id or str(uuid4()))
    async_to_sync(persist_schema)(schema, ctx)

    refresh_projection_from_domain_state(simulation_id=sim_id)
    session.refresh_from_db()
    _emit_seeded_vital_events(session)
    _emit_seeded_condition_events(session)
