from pathlib import Path
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError

from api.v1.schemas.trainerlab import VitalCreateIn
from apps.common.models import OutboxEvent
from apps.common.outbox import event_types as outbox_events
from apps.accounts.models import UserRole
from apps.trainerlab.models import RuntimeEvent, SessionStatus
from apps.trainerlab.services import complete_initial_scenario_generation, create_session

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

    assert "outbox_events.SIMULATION_PRESET_APPLIED" in source
    assert ":{session.id}:{instruction.id}:{command.id}" in source
    assert "trainerlab.preset.applied:{session.id}:{instruction.id}:{command.id}" not in source


class TrainerSessionLifecycleEventTests(TestCase):
    def setUp(self) -> None:
        self.role = UserRole.objects.create(title="Trainer")
        self.user = User.objects.create_user(
            email="trainer@example.com",
            password="password",
            role=self.role,
        )

    @patch("apps.trainerlab.services.generate_fake_name", new_callable=AsyncMock)
    def test_create_session_seeding_emits_canonical_status_updated(self, mock_name: AsyncMock) -> None:
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
        self.assertFalse(OutboxEvent.objects.filter(event_type="session.seeded").exists())
        self.assertFalse(RuntimeEvent.objects.filter(event_type="session.seeded").exists())

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
        self.assertFalse(OutboxEvent.objects.filter(event_type="session.seeded").exists())

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
        self.assertEqual(seeded_event.payload["state_revision"], session.runtime_state_json["state_revision"])
        self.assertEqual(seeded_event.payload["call_id"], "call-123")
        self.assertFalse(OutboxEvent.objects.filter(event_type="session.seeded").exists())
        self.assertFalse(RuntimeEvent.objects.filter(event_type="session.seeded").exists())
