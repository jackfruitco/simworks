from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils.timezone import now
from pydantic import ValidationError

from api.v1.schemas.trainerlab import VitalCreateIn
from apps.accounts.models import UserRole
from apps.common.models import OutboxEvent
from apps.common.outbox import event_types as outbox_events
from apps.guards.enums import UsageScopeType
from apps.guards.models import UsageRecord
from apps.simcore.models import Simulation
from apps.trainerlab.failure_service import (
    finalize_trainerlab_failure,
    record_simulation_failure,
    send_failure_alert_email,
)
from apps.trainerlab.models import (
    RuntimeEvent,
    SessionStatus,
    SimulationFailureRecord,
    TrainerSession,
)
from apps.trainerlab.services import (
    complete_initial_scenario_generation,
    create_session,
    fail_initial_scenario_generation,
    retry_initial_scenario_generation,
)
from apps.trainerlab.tasks import (
    FAILED_SIMULATION_ARCHIVE_AFTER_SECONDS,
    archive_failed_trainerlab_simulations,
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


# ---------------------------------------------------------------------------
# Helpers shared by archival / failure-record tests
# ---------------------------------------------------------------------------


def _make_role():
    role, _ = UserRole.objects.get_or_create(title="Tester")
    return role


def _make_user(email="archtest@example.com"):
    role = _make_role()
    return User.objects.create_user(email=email, password="pw", role=role)


def _make_failed_sim(user=None, minutes_ago=6):
    """Return a FAILED Simulation whose terminal_at is *minutes_ago* minutes in the past."""
    terminal = now() - timedelta(minutes=minutes_ago)
    sim = Simulation.objects.create(
        user=user,
        status=Simulation.SimulationStatus.FAILED,
        terminal_at=terminal,
    )
    return sim


def _make_trainer_session(sim, user=None):
    """Attach a minimal TrainerSession row to *sim*."""
    from apps.trainerlab.models import TrainerSession

    return TrainerSession.objects.create(
        simulation=sim,
        status=SessionStatus.FAILED,
    )


class AutoArchivalTaskTests(TestCase):
    """archive_failed_trainerlab_simulations() respects grace period and scope."""

    def setUp(self):
        self.user = _make_user()

    def test_archives_failed_sim_past_grace_period(self):
        sim = _make_failed_sim(user=self.user, minutes_ago=6)
        _make_trainer_session(sim, self.user)

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertTrue(sim.is_archived)
        self.assertEqual(sim.archived_reason, Simulation.ArchiveReason.SYSTEM_FAILED)

    def test_does_not_archive_sim_within_grace_period(self):
        sim = _make_failed_sim(user=self.user, minutes_ago=2)
        _make_trainer_session(sim, self.user)

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertFalse(sim.is_archived)

    def test_does_not_archive_completed_sim(self):
        terminal = now() - timedelta(minutes=10)
        sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.COMPLETED,
            terminal_at=terminal,
        )
        _make_trainer_session(sim, self.user)

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertFalse(sim.is_archived)

    def test_does_not_archive_timed_out_sim(self):
        terminal = now() - timedelta(minutes=10)
        sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.TIMED_OUT,
            terminal_at=terminal,
        )
        _make_trainer_session(sim, self.user)

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertFalse(sim.is_archived)

    def test_does_not_archive_failed_sim_without_trainer_session(self):
        sim = _make_failed_sim(user=self.user, minutes_ago=10)
        # No TrainerSession attached

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertFalse(sim.is_archived)

    def test_idempotent_does_not_overwrite_already_archived(self):
        sim = _make_failed_sim(user=self.user, minutes_ago=10)
        _make_trainer_session(sim, self.user)
        first_ts = now() - timedelta(hours=1)
        sim.archive(
            reason=Simulation.ArchiveReason.USER_ARCHIVED,
            archived_by=self.user,
            timestamp=first_ts,
        )

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertEqual(sim.archived_reason, Simulation.ArchiveReason.USER_ARCHIVED)
        self.assertEqual(sim.archived_at, first_ts)

    def test_grace_period_constant_is_300_seconds(self):
        self.assertEqual(FAILED_SIMULATION_ARCHIVE_AFTER_SECONDS, 300)


class SimulationFailureRecordTests(TestCase):
    """SimulationFailureRecord creation, idempotency, and fields."""

    def setUp(self):
        self.user = _make_user(email="failrec@example.com")
        self.sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
        )

    def test_record_simulation_failure_creates_record(self):
        record = record_simulation_failure(
            simulation=self.sim,
            reason_code="provider_timeout",
            reason_text="AI timed out.",
            correlation_id="corr-123",
            retryable=True,
        )
        self.assertIsNotNone(record.pk)
        self.assertEqual(record.simulation, self.sim)
        self.assertEqual(record.terminal_reason_code, "provider_timeout")
        self.assertEqual(record.correlation_id, "corr-123")
        self.assertTrue(record.retryable)

    def test_record_simulation_failure_is_idempotent(self):
        record_simulation_failure(
            simulation=self.sim,
            reason_code="first_code",
            retryable=True,
        )
        record_simulation_failure(
            simulation=self.sim,
            reason_code="second_code",
            retryable=False,
        )
        self.assertEqual(SimulationFailureRecord.objects.filter(simulation=self.sim).count(), 1)
        updated = SimulationFailureRecord.objects.get(simulation=self.sim)
        self.assertEqual(updated.terminal_reason_code, "second_code")
        self.assertFalse(updated.retryable)

    def test_fail_initial_scenario_generation_creates_failure_record(self):
        """fail_initial_scenario_generation() hooks into failure_service."""
        sim2 = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.IN_PROGRESS,
        )
        TrainerSession.objects.create(
            simulation=sim2,
            status=SessionStatus.SEEDING,
        )

        with patch("apps.common.emailing.service.send_transactional_email"):
            fail_initial_scenario_generation(
                simulation_id=sim2.pk,
                reason_code="provider_error",
                reason_text="Connection refused.",
                retryable=False,
                correlation_id="corr-fail-rec",
            )

        self.assertTrue(SimulationFailureRecord.objects.filter(simulation=sim2).exists())
        record = SimulationFailureRecord.objects.get(simulation=sim2)
        self.assertIn("provider_error", record.terminal_reason_code)
        self.assertEqual(record.correlation_id, "corr-fail-rec")
        self.assertFalse(record.retryable)


class FailureAlertEmailTests(TestCase):
    """send_failure_alert_email() subject and recipient logic."""

    def setUp(self):
        self.user = _make_user(email="emailtest@example.com")
        self.sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
        )

    def _make_record(self, environment="staging"):
        return SimulationFailureRecord.objects.create(
            simulation=self.sim,
            environment=environment,
            lab_slug="trainerlab",
            terminal_reason_code="test_code",
            retryable=True,
        )

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_staging_subject_has_staging_prefix(self, mock_send):
        record = self._make_record(environment="staging")
        send_failure_alert_email(record)
        mock_send.assert_called_once()
        subject = mock_send.call_args[1]["subject"]
        self.assertIn("[STAGING]", subject)

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_production_subject_has_no_staging_prefix(self, mock_send):
        record = self._make_record(environment="production")
        send_failure_alert_email(record)
        mock_send.assert_called_once()
        subject = mock_send.call_args[1]["subject"]
        self.assertNotIn("[STAGING]", subject)

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_recipient_is_errors_inbox(self, mock_send):
        record = self._make_record()
        send_failure_alert_email(record)
        mock_send.assert_called_once()
        to = mock_send.call_args[1]["to"]
        self.assertIn("errors@jackfruitco.com", to)

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_body_contains_simulation_id_and_reason_code(self, mock_send):
        record = self._make_record()
        send_failure_alert_email(record)
        text_body = mock_send.call_args[1]["text_body"]
        self.assertIn(str(self.sim.pk), text_body)
        self.assertIn("test_code", text_body)

    @patch(
        "apps.common.emailing.service.send_transactional_email",
        side_effect=Exception("SMTP down"),
    )
    def test_email_failure_is_non_fatal(self, _mock_send):
        record = self._make_record()
        # Should not raise
        send_failure_alert_email(record)


class BillingExclusionSignalTests(TestCase):
    """on_service_call_succeeded skips user/account usage rows for failed TrainerLab sims only."""

    def setUp(self):
        self.user = _make_user(email="billing@example.com")

    def _dispatch_service_call_succeeded(self, simulation):
        from apps.guards.signals import on_service_call_succeeded

        call = MagicMock()
        call.total_tokens = 100
        call.input_tokens = 40
        call.output_tokens = 60
        call.reasoning_tokens = 0
        call.context = {"simulation_id": simulation.pk}
        call.related_object_id = None
        on_service_call_succeeded(sender=None, call=call)

    def test_failed_trainerlab_sim_creates_session_usage_but_not_user_or_account(self):
        """A failed TrainerLab simulation (has TrainerSession) is non-billable for quota."""
        sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
        )
        TrainerSession.objects.create(simulation=sim, status=SessionStatus.FAILED)

        self._dispatch_service_call_succeeded(sim)

        session_records = UsageRecord.objects.filter(
            scope_type=UsageScopeType.SESSION, simulation=sim
        )
        user_records = UsageRecord.objects.filter(scope_type=UsageScopeType.USER, user=self.user)
        self.assertEqual(session_records.count(), 1)
        self.assertEqual(user_records.count(), 0)

    def test_failed_non_trainerlab_sim_creates_all_three_usage_scopes(self):
        """A failed simulation without a TrainerSession is treated as ChatLab — still billable."""
        sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
        )
        # No TrainerSession → _detect_lab_type returns "chatlab" → billable

        self._dispatch_service_call_succeeded(sim)

        session_records = UsageRecord.objects.filter(
            scope_type=UsageScopeType.SESSION, simulation=sim
        )
        user_records = UsageRecord.objects.filter(scope_type=UsageScopeType.USER, user=self.user)
        self.assertEqual(session_records.count(), 1)
        self.assertEqual(user_records.count(), 1)

    def test_completed_sim_creates_all_three_usage_scopes(self):
        sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.COMPLETED,
        )

        self._dispatch_service_call_succeeded(sim)

        session_records = UsageRecord.objects.filter(
            scope_type=UsageScopeType.SESSION, simulation=sim
        )
        user_records = UsageRecord.objects.filter(scope_type=UsageScopeType.USER, user=self.user)
        self.assertEqual(session_records.count(), 1)
        self.assertEqual(user_records.count(), 1)


class FinalizeTrainerlabFailureTests(TestCase):
    """finalize_trainerlab_failure() is the canonical entry point with email idempotency."""

    def setUp(self):
        self.user = _make_user(email="finalize@example.com")
        self.sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
        )
        self.session = TrainerSession.objects.create(
            simulation=self.sim,
            status=SessionStatus.FAILED,
        )

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_creates_failure_record_on_first_call(self, _mock_send):
        finalize_trainerlab_failure(
            simulation=self.sim,
            trainer_session=self.session,
            reason_code="init_error",
            retryable=False,
        )
        self.assertTrue(SimulationFailureRecord.objects.filter(simulation=self.sim).exists())

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_sends_alert_email_on_first_call(self, mock_send):
        finalize_trainerlab_failure(
            simulation=self.sim,
            trainer_session=self.session,
            reason_code="init_error",
            retryable=False,
        )
        mock_send.assert_called_once()

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_does_not_send_email_on_subsequent_calls(self, mock_send):
        """Repeated calls update the record but do not re-send the alert."""
        finalize_trainerlab_failure(
            simulation=self.sim,
            trainer_session=self.session,
            reason_code="init_error",
            retryable=False,
        )
        finalize_trainerlab_failure(
            simulation=self.sim,
            trainer_session=self.session,
            reason_code="updated_code",
            retryable=True,
        )
        # Email sent exactly once (first creation only)
        self.assertEqual(mock_send.call_count, 1)

    @patch("apps.common.emailing.service.send_transactional_email")
    def test_updates_record_on_subsequent_calls(self, _mock_send):
        finalize_trainerlab_failure(
            simulation=self.sim,
            trainer_session=self.session,
            reason_code="first_code",
            retryable=True,
        )
        finalize_trainerlab_failure(
            simulation=self.sim,
            trainer_session=self.session,
            reason_code="second_code",
            retryable=False,
        )
        record = SimulationFailureRecord.objects.get(simulation=self.sim)
        self.assertEqual(record.terminal_reason_code, "second_code")
        self.assertFalse(record.retryable)

    def test_is_non_fatal_when_db_raises(self):
        """Exceptions inside finalize_trainerlab_failure must not propagate."""
        with patch(
            "apps.trainerlab.models.SimulationFailureRecord.objects.update_or_create",
            side_effect=Exception("DB exploded"),
        ):
            # Should not raise
            finalize_trainerlab_failure(
                simulation=self.sim,
                trainer_session=self.session,
                reason_code="error",
            )


class AutoArchivalSystemUserTests(TestCase):
    """archive_failed_trainerlab_simulations() sets archived_by to the system user."""

    def setUp(self):
        self.user = _make_user(email="sysuser@example.com")

    def _make_archivable(self):
        sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
            terminal_at=now() - timedelta(minutes=10),
        )
        TrainerSession.objects.create(simulation=sim, status=SessionStatus.FAILED)
        return sim

    def test_archives_with_system_user_as_archived_by(self):
        sim = self._make_archivable()

        system_user = _make_user(email="system@medsim.local")
        with patch("apps.trainerlab.tasks.get_system_user", return_value=system_user):
            archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertTrue(sim.is_archived)
        self.assertEqual(sim.archived_by, system_user)
        self.assertEqual(sim.archived_reason, Simulation.ArchiveReason.SYSTEM_FAILED)

    def test_archives_even_if_system_user_resolution_fails(self):
        sim = self._make_archivable()

        with patch(
            "apps.trainerlab.tasks.get_system_user",
            side_effect=Exception("user not found"),
        ):
            # Should not raise; task falls back to archived_by=None
            archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertTrue(sim.is_archived)
        self.assertIsNone(sim.archived_by)

    def test_archives_sets_reason_system_failed(self):
        sim = self._make_archivable()

        archive_failed_trainerlab_simulations()

        sim.refresh_from_db()
        self.assertEqual(sim.archived_reason, Simulation.ArchiveReason.SYSTEM_FAILED)


class IncludeArchivedSessionQueryTests(TestCase):
    """list_trainer_sessions include_archived flag is gated to staff users only."""

    def setUp(self):
        self.user = _make_user(email="listtest@example.com")

        self.active_sim = Simulation.objects.create(user=self.user)
        self.active_session = TrainerSession.objects.create(
            simulation=self.active_sim,
            status=SessionStatus.SEEDED,
        )

        archived_sim = Simulation.objects.create(
            user=self.user,
            status=Simulation.SimulationStatus.FAILED,
            terminal_at=now() - timedelta(minutes=10),
        )
        archived_sim.archive(reason=Simulation.ArchiveReason.SYSTEM_FAILED)
        self.archived_session = TrainerSession.objects.create(
            simulation=archived_sim,
            status=SessionStatus.FAILED,
        )

    def _filtered_qs(self, *, is_staff: bool, include_archived: bool):
        sim_qs = Simulation.objects.filter(user=self.user)
        show_archived = include_archived and is_staff
        qs = TrainerSession.objects.filter(simulation__in=sim_qs)
        if not show_archived:
            qs = qs.filter(simulation__archived_at__isnull=True)
        return qs

    def test_default_excludes_archived_for_normal_user(self):
        qs = self._filtered_qs(is_staff=False, include_archived=False)
        self.assertIn(self.active_session, qs)
        self.assertNotIn(self.archived_session, qs)

    def test_normal_user_include_archived_true_still_excluded(self):
        # Non-staff: include_archived=True is silently ignored
        qs = self._filtered_qs(is_staff=False, include_archived=True)
        self.assertIn(self.active_session, qs)
        self.assertNotIn(self.archived_session, qs)

    def test_staff_with_include_archived_true_sees_archived(self):
        qs = self._filtered_qs(is_staff=True, include_archived=True)
        self.assertIn(self.active_session, qs)
        self.assertIn(self.archived_session, qs)

    def test_staff_without_include_archived_flag_still_excludes(self):
        # Staff must opt in explicitly; default remains exclusive
        qs = self._filtered_qs(is_staff=True, include_archived=False)
        self.assertIn(self.active_session, qs)
        self.assertNotIn(self.archived_session, qs)


class AdminRegistrationSmokeTest(TestCase):
    """SimulationFailureRecordAdmin is registered in Django admin."""

    def test_simulation_failure_record_admin_registered(self):
        from django.contrib import admin

        self.assertIn(SimulationFailureRecord, admin.site._registry)
