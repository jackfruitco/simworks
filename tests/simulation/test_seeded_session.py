"""Tests for TrainerLab initial seeding lifecycle and seeded event emission."""

from __future__ import annotations

from uuid import uuid4

from asgiref.sync import async_to_sync
from django.utils import timezone
import pytest

from apps.common.outbox import event_types as outbox_events
from apps.trainerlab.orca.schemas import InitialScenarioSchema
from apps.trainerlab.orca.services import GenerateInitialScenario
from apps.trainerlab.services import (
    _emit_seeded_condition_events,
    _emit_seeded_vital_events,
    complete_initial_scenario_generation,
    create_session,
    create_session_with_initial_generation,
    fail_initial_scenario_generation,
    retry_initial_scenario_generation,
)
from orchestrai_django.models import CallStatus, ServiceCall
from orchestrai_django.persistence import PersistContext, persist_schema
from orchestrai_django.signals import ai_response_failed, service_call_succeeded
from orchestrai_django.tasks import process_pending_persistence


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


def _persist_initial_payload(*, simulation_id: int, call_id: str) -> None:
    schema = InitialScenarioSchema.model_validate(_make_initial_payload())
    ctx = PersistContext(simulation_id=simulation_id, call_id=call_id)
    async_to_sync(persist_schema)(schema, ctx)


def _create_pending_initial_service_call(*, session, call_id=None) -> ServiceCall:
    return ServiceCall.objects.create(
        id=call_id or uuid4(),
        service_identity=GenerateInitialScenario.identity.as_str,
        status=CallStatus.COMPLETED,
        finished_at=timezone.now(),
        schema_fqn=f"{InitialScenarioSchema.__module__}.{InitialScenarioSchema.__qualname__}",
        output_data=_make_initial_payload(),
        context={
            "simulation_id": session.simulation_id,
            "correlation_id": f"corr-{uuid4()}",
        },
        related_object_id=str(session.simulation_id),
    )


def _phase_event_count(queryset, *, phase: str) -> int:
    return sum(
        1 for payload in queryset.values_list("payload", flat=True) if payload.get("phase") == phase
    )


class TestGenerateInitialScenarioSchemaValid:
    @pytest.mark.unit
    def test_schema_importable_and_valid(self):
        assert InitialScenarioSchema is not None
        assert hasattr(InitialScenarioSchema, "model_fields")


@pytest.mark.django_db(transaction=True)
class TestSeedingSessionLifecycle:
    def test_create_session_with_initial_generation_returns_seeding(self, user, monkeypatch):
        from apps.trainerlab.models import RuntimeEvent

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            lambda **kwargs: "fake-call-id-seeding",
        )

        session, call_id = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )

        assert call_id == "fake-call-id-seeding"
        assert session.status == "seeding"
        assert session.runtime_state_json["phase"] == "seeding"
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeding") == 1
        assert _phase_event_count(runtime_status_events, phase="seeded") == 0

    def test_complete_initial_scenario_generation_marks_seeded_and_emits_events(
        self, user, monkeypatch
    ):
        from apps.trainerlab.models import RuntimeEvent

        monkeypatch.setattr(
            "apps.trainerlab.orca.schemas.initial._complete_initial_generation_after_persist",
            lambda context: None,
        )
        monkeypatch.setattr(
            "apps.trainerlab.signals._is_initial_generation_service",
            lambda service_identity: False,
        )
        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            lambda **kwargs: "fake-call-id-complete",
        )

        session, call_id = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )
        _persist_initial_payload(
            simulation_id=session.simulation_id, call_id=call_id or str(uuid4())
        )
        session.refresh_from_db()
        assert session.status == "seeding"
        assert session.runtime_state_json["phase"] == "seeding"
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeded") == 0

        completed = complete_initial_scenario_generation(
            simulation_id=session.simulation_id,
            call_id=call_id,
        )
        assert completed is not None

        session.refresh_from_db()
        assert session.status == "seeded"
        assert session.runtime_state_json["phase"] == "seeded"
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeded") == 1
        assert (
            RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.PATIENT_VITAL_CREATED,
            ).count()
            >= 1
        )
        assert (
            RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.PATIENT_INJURY_CREATED,
            ).count()
            + RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.PATIENT_ILLNESS_CREATED,
            ).count()
        ) >= 1
        assert (
            RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.PATIENT_PROBLEM_CREATED,
            ).count()
            >= 1
        )

    def test_service_call_succeeded_signal_accepts_canonical_identity(self, user, monkeypatch):
        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            lambda **kwargs: str(uuid4()),
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )
        captured = []
        monkeypatch.setattr(
            "apps.trainerlab.signals.complete_initial_scenario_generation",
            lambda **kwargs: captured.append(kwargs),
        )

        service_call_succeeded.send(
            sender=self.__class__,
            call=type(
                "Call",
                (),
                {
                    "domain_persisted": True,
                    "context": {
                        "simulation_id": session.simulation_id,
                        "correlation_id": "corr-signal",
                    },
                },
            )(),
            service_identity=GenerateInitialScenario.identity.as_str,
            context={"simulation_id": session.simulation_id, "correlation_id": "corr-signal"},
        )

        assert captured == [
            {
                "simulation_id": session.simulation_id,
                "correlation_id": "corr-signal",
                "call_id": None,
            }
        ]

    def test_process_pending_persistence_marks_seeded_and_emits_runtime_and_outbox_once(self, user):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import RuntimeEvent, SessionStatus

        session = create_session(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
            status=SessionStatus.SEEDING,
            emit_seeded_event=False,
        )
        call = _create_pending_initial_service_call(session=session)

        stats = process_pending_persistence.call()

        call.refresh_from_db()
        session.refresh_from_db()
        assert stats["claimed"] == 1
        assert stats["processed"] == 1
        assert call.domain_persisted is True
        assert session.status == SessionStatus.SEEDED
        assert session.runtime_state_json["phase"] == "seeded"
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        outbox_status_events = OutboxEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeded") == 1
        assert _phase_event_count(outbox_status_events, phase="seeded") == 1

    def test_process_pending_persistence_uses_authoritative_post_persist_when_signal_ignored(
        self, user, monkeypatch
    ):
        from apps.trainerlab.models import RuntimeEvent, SessionStatus

        monkeypatch.setattr(
            "apps.trainerlab.signals._is_initial_generation_service",
            lambda service_identity: False,
        )

        session = create_session(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
            status=SessionStatus.SEEDING,
            emit_seeded_event=False,
        )
        call = _create_pending_initial_service_call(session=session)

        stats = process_pending_persistence.call()

        call.refresh_from_db()
        session.refresh_from_db()
        assert stats["processed"] == 1
        assert call.domain_persisted is True
        assert session.status == SessionStatus.SEEDED
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeded") == 1

    def test_duplicate_success_trigger_is_idempotent_after_deferred_completion(self, user):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import RuntimeEvent, SessionStatus

        session = create_session(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
            status=SessionStatus.SEEDING,
            emit_seeded_event=False,
        )
        call = _create_pending_initial_service_call(session=session)

        process_pending_persistence.call()
        call.refresh_from_db()
        service_call_succeeded.send(
            sender=self.__class__,
            call=call,
            call_id=call.id,
            service_identity=GenerateInitialScenario.identity.as_str,
            context=call.context,
        )

        session.refresh_from_db()
        assert session.status == SessionStatus.SEEDED
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        outbox_status_events = OutboxEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeded") == 1
        assert _phase_event_count(outbox_status_events, phase="seeded") == 1

    def test_fail_initial_scenario_generation_marks_failed(self, user, monkeypatch):
        from apps.trainerlab.models import RuntimeEvent

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            lambda **kwargs: "fake-call-id-failed",
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )

        fail_initial_scenario_generation(
            simulation_id=session.simulation_id,
            reason_code="provider_timeout",
            reason_text="Timed out waiting for initial scenario generation.",
            retryable=True,
        )

        session.refresh_from_db()
        session.simulation.refresh_from_db()
        assert session.status == "failed"
        assert session.runtime_state_json["phase"] == "failed"
        assert session.runtime_state_json["initial_generation_retryable"] is True
        assert session.simulation.status == "failed"
        assert (
            session.simulation.terminal_reason_code
            == "trainerlab_initial_generation_provider_timeout"
        )
        assert (
            _phase_event_count(
                RuntimeEvent.objects.filter(
                    simulation_id=session.simulation_id,
                    event_type=outbox_events.SIMULATION_STATUS_UPDATED,
                ),
                phase="failed",
            )
            == 1
        )

    def test_retry_initial_scenario_generation_resets_phase_without_duplicate_status_event(
        self, user, monkeypatch
    ):
        from apps.trainerlab.models import RuntimeEvent

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            lambda **kwargs: "fake-call-id-retry",
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )
        fail_initial_scenario_generation(
            simulation_id=session.simulation_id,
            reason_code="provider_timeout",
            reason_text="Timed out waiting for initial scenario generation.",
            retryable=True,
        )

        session.refresh_from_db()
        retry_initial_scenario_generation(session=session, correlation_id="corr-retry")

        session.refresh_from_db()
        assert session.status == "seeding"
        assert session.runtime_state_json["phase"] == "seeding"
        runtime_status_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        )
        assert _phase_event_count(runtime_status_events, phase="seeding") == 1
        assert _phase_event_count(runtime_status_events, phase="failed") == 1

    def test_ai_response_failed_signal_marks_failed(self, user, monkeypatch):
        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            lambda **kwargs: "fake-call-id-signal-failed",
        )

        session, _ = create_session_with_initial_generation(
            user=user,
            scenario_spec={"diagnosis": "undifferentiated trauma"},
            directives=None,
            modifiers=[],
        )
        call = ServiceCall.objects.create(
            service_identity=GenerateInitialScenario.identity.as_str,
            status=CallStatus.FAILED,
            context={"simulation_id": session.simulation_id},
            error="Timed out waiting for provider response",
        )

        ai_response_failed.send(
            sender=self.__class__,
            call_id=call.id,
            error="Timed out waiting for provider response",
            reason_code="provider_timeout",
            user_retryable=True,
        )

        session.refresh_from_db()
        session.simulation.refresh_from_db()
        assert session.status == "failed"
        assert session.runtime_state_json["phase"] == "failed"
        assert session.simulation.status == "failed"
        assert session.simulation.terminal_reason_code.endswith("provider_timeout")


@pytest.mark.django_db(transaction=True)
class TestEmitSeededVitalEvents:
    def test_emits_one_event_per_vital_type(self, user):
        from apps.trainerlab.models import RuntimeEvent

        session = create_session(
            user=user,
            scenario_spec={},
            directives=None,
            modifiers=[],
        )

        _persist_initial_payload(simulation_id=session.simulation_id, call_id=str(uuid4()))
        session.refresh_from_db()
        _emit_seeded_vital_events(session)

        events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.PATIENT_VITAL_CREATED,
        )
        assert events.count() >= 1

    def test_emits_one_event_per_condition(self, user):
        from apps.trainerlab.models import RuntimeEvent

        session = create_session(
            user=user,
            scenario_spec={},
            directives=None,
            modifiers=[],
        )

        _persist_initial_payload(simulation_id=session.simulation_id, call_id=str(uuid4()))
        session.refresh_from_db()
        _emit_seeded_condition_events(session)

        cause_events = (
            RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.PATIENT_INJURY_CREATED,
            ).count()
            + RuntimeEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.PATIENT_ILLNESS_CREATED,
            ).count()
        )
        problem_events = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.PATIENT_PROBLEM_CREATED,
        ).count()
        assert cause_events >= 1
        assert problem_events >= 1
