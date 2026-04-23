from pathlib import Path
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError

from api.v1.schemas.trainerlab import VitalCreateIn
from apps.accounts.models import UserRole
from apps.common.models import OutboxEvent
from apps.common.outbox import event_types as outbox_events
from apps.trainerlab.models import RuntimeEvent, SessionStatus
from apps.trainerlab.services import (
    complete_initial_scenario_generation,
    create_session,
    fail_initial_scenario_generation,
    retry_initial_scenario_generation,
)

User = get_user_model()


class VitalCreateInSchemaTests(SimpleTestCase):
    def test_accepts_respiratory_rate_vital_type(self) -> None:
        payload = {
            "vital_type": "respiratory_rate",
            "min_value": 12,
            "max_value": 20,
            "lock_value": False,
        }

        vital = VitalCreateIn.model_validate(payload)

        self.assertEqual(vital.vital_type, "respiratory_rate")

    def test_rejects_unknown_vital_type(self) -> None:
        payload = {
            "vital_type": "temperature",
            "min_value": 98,
            "max_value": 100,
            "lock_value": False,
        }

        with self.assertRaises(ValidationError):
            VitalCreateIn.model_validate(payload)


def test_apply_preset_outbox_idempotency_key_includes_command_id():
    source = Path("SimWorks/api/v1/endpoints/trainerlab.py").read_text()
    (legacy_preset_alias,) = outbox_events.legacy_aliases_for(
        outbox_events.SIMULATION_PRESET_APPLIED
    )

    assert "outbox_events.SIMULATION_PRESET_APPLIED" in source
    assert ":{session.id}:{instruction.id}:{command.id}" in source
    assert f"{legacy_preset_alias}:{{session.id}}:{{instruction.id}}:{{command.id}}" not in source


class TrainerSessionLifecycleEventTests(TestCase):
    def setUp(self) -> None:
        self.role = UserRole.objects.create(title="Trainer")
        self.user = User.objects.create_user(
            email="trainer@example.com",
            password="password",
            role=self.role,
        )

    @patch("apps.trainerlab.services.generate_fake_name", new_callable=AsyncMock)
    def test_create_session_seeding_emits_canonical_status_updated(
        self, mock_name: AsyncMock
    ) -> None:
        mock_name.return_value = "Test User"

        session = create_session(
            user=self.user,
            scenario_spec={"diagnosis": "Trauma"},
            directives="Seed the scenario",
            modifiers=["combat"],
            status=SessionStatus.SEEDING,
            emit_seeded_event=False,
            correlation_id="corr-seeding",
        )

        outbox_event = OutboxEvent.objects.get(
            idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:seeding"
        )
        runtime_event = RuntimeEvent.objects.get(session=session)

        self.assertEqual(outbox_event.event_type, outbox_events.SIMULATION_STATUS_UPDATED)
        self.assertEqual(outbox_event.correlation_id, "corr-seeding")
        self.assertEqual(outbox_event.payload["status"], SessionStatus.SEEDING)
        self.assertEqual(outbox_event.payload["phase"], "seeding")
        self.assertEqual(outbox_event.payload["scenario_spec"]["modifiers"], ["combat"])
        self.assertEqual(outbox_event.payload["state_revision"], 0)
        self.assertNotIn("from", outbox_event.payload)
        self.assertNotIn("to", outbox_event.payload)
        self.assertEqual(runtime_event.event_type, outbox_events.SIMULATION_STATUS_UPDATED)
        legacy_status_aliases = outbox_events.legacy_aliases_for(
            outbox_events.SIMULATION_STATUS_UPDATED
        )
        self.assertFalse(OutboxEvent.objects.filter(event_type__in=legacy_status_aliases).exists())
        self.assertFalse(RuntimeEvent.objects.filter(event_type__in=legacy_status_aliases).exists())

    @patch("apps.trainerlab.services.generate_fake_name", new_callable=AsyncMock)
    def test_create_session_seeded_emits_seeded_status_updated(self, mock_name: AsyncMock) -> None:
        mock_name.return_value = "Test User"

        session = create_session(
            user=self.user,
            scenario_spec={"chief_complaint": "Chest pain"},
            directives="Ready to run",
            modifiers=["trauma"],
            status=SessionStatus.SEEDED,
            emit_seeded_event=True,
            correlation_id="corr-seeded",
        )

        outbox_event = OutboxEvent.objects.get(
            idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:seeded"
        )

        self.assertEqual(outbox_event.event_type, outbox_events.SIMULATION_STATUS_UPDATED)
        self.assertEqual(outbox_event.correlation_id, "corr-seeded")
        self.assertEqual(outbox_event.payload["status"], SessionStatus.SEEDED)
        self.assertEqual(outbox_event.payload["phase"], "seeded")
        self.assertEqual(outbox_event.payload["scenario_spec"]["modifiers"], ["trauma"])
        self.assertEqual(outbox_event.payload["state_revision"], 0)
        legacy_status_aliases = outbox_events.legacy_aliases_for(
            outbox_events.SIMULATION_STATUS_UPDATED
        )
        self.assertFalse(OutboxEvent.objects.filter(event_type__in=legacy_status_aliases).exists())

    @patch("apps.trainerlab.services.generate_fake_name", new_callable=AsyncMock)
    def test_complete_initial_generation_updates_state_and_emits_seeded_status_event(
        self, mock_name: AsyncMock
    ) -> None:
        mock_name.return_value = "Test User"

        session = create_session(
            user=self.user,
            scenario_spec={"diagnosis": "Shock"},
            directives="Begin seeding",
            modifiers=["military"],
            status=SessionStatus.SEEDING,
            emit_seeded_event=False,
            correlation_id="corr-create",
        )

        complete_initial_scenario_generation(
            simulation_id=session.simulation_id,
            correlation_id="corr-complete",
            call_id="call-123",
        )

        session.refresh_from_db()
        seeded_event = OutboxEvent.objects.get(
            idempotency_key=f"{outbox_events.SIMULATION_STATUS_UPDATED}:{session.id}:seeded"
        )

        self.assertEqual(session.status, SessionStatus.SEEDED)
        self.assertEqual(session.runtime_state_json["phase"], "seeded")
        self.assertEqual(session.runtime_state_json["last_runtime_error"], "")
        self.assertIsNone(session.runtime_state_json["initial_generation_retryable"])
        self.assertEqual(seeded_event.event_type, outbox_events.SIMULATION_STATUS_UPDATED)
        self.assertEqual(seeded_event.correlation_id, "corr-complete")
        self.assertEqual(seeded_event.payload["status"], SessionStatus.SEEDED)
        self.assertEqual(seeded_event.payload["phase"], "seeded")
        self.assertEqual(seeded_event.payload["from"], SessionStatus.SEEDING)
        self.assertEqual(seeded_event.payload["to"], SessionStatus.SEEDED)
        self.assertEqual(seeded_event.payload["scenario_spec"]["modifiers"], ["military"])
        self.assertEqual(
            seeded_event.payload["state_revision"], session.runtime_state_json["state_revision"]
        )
        self.assertEqual(seeded_event.payload["call_id"], "call-123")
        legacy_status_aliases = outbox_events.legacy_aliases_for(
            outbox_events.SIMULATION_STATUS_UPDATED
        )
        self.assertFalse(OutboxEvent.objects.filter(event_type__in=legacy_status_aliases).exists())
        self.assertFalse(RuntimeEvent.objects.filter(event_type__in=legacy_status_aliases).exists())

    @patch("apps.trainerlab.services.enqueue_initial_scenario_generation", return_value="call-456")
    @patch("apps.trainerlab.services.generate_fake_name", new_callable=AsyncMock)
    def test_failure_and_retry_emit_normalized_status_events_once(
        self, mock_name: AsyncMock, _mock_enqueue
    ) -> None:
        mock_name.return_value = "Casey Patient"

        session = create_session(
            user=self.user,
            scenario_spec={"diagnosis": "Shock", "chief_complaint": "Weakness"},
            directives="Begin seeding",
            modifiers=[],
            status=SessionStatus.SEEDING,
            emit_seeded_event=False,
            correlation_id="corr-create",
        )

        fail_initial_scenario_generation(
            simulation_id=session.simulation_id,
            reason_code="provider_timeout",
            reason_text="Timed out.",
            retryable=True,
            correlation_id="corr-fail",
        )
        session.refresh_from_db()

        retry_initial_scenario_generation(session=session, correlation_id="corr-retry")
        session.refresh_from_db()

        status_events = list(
            OutboxEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type=outbox_events.SIMULATION_STATUS_UPDATED,
            ).order_by("created_at", "id")
        )
        self.assertEqual(len(status_events), 3)
        self.assertEqual(
            [event.payload["status"] for event in status_events],
            [
                SessionStatus.SEEDING,
                SessionStatus.FAILED,
                SessionStatus.SEEDING,
            ],
        )

        failed_payload = status_events[1].payload
        self.assertEqual(failed_payload["lab_slug"], "trainerlab")
        self.assertEqual(failed_payload["from"], SessionStatus.SEEDING)
        self.assertEqual(failed_payload["to"], SessionStatus.FAILED)
        self.assertEqual(failed_payload["retryable"], True)
        self.assertEqual(failed_payload["patient_name"], "Casey Patient")
        self.assertEqual(failed_payload["chief_complaint"], "Weakness")
        self.assertEqual(failed_payload["diagnosis"], "Shock")
        self.assertEqual(
            failed_payload["terminal_reason_code"],
            "trainerlab_initial_generation_provider_timeout",
        )
        self.assertEqual(failed_payload["reason_code"], failed_payload["terminal_reason_code"])
        self.assertIn("created_at", failed_payload)
        self.assertIn("updated_at", failed_payload)
        self.assertIn("state_revision", failed_payload)

        retry_payload = status_events[2].payload
        self.assertEqual(retry_payload["from"], SessionStatus.FAILED)
        self.assertEqual(retry_payload["to"], SessionStatus.SEEDING)
        self.assertIsNone(retry_payload["terminal_reason_code"])
        self.assertEqual(retry_payload["lab_slug"], "trainerlab")

        runtime_status_count = RuntimeEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type=outbox_events.SIMULATION_STATUS_UPDATED,
        ).count()
        self.assertEqual(runtime_status_count, 3)
