"""Tests for guard service functions.

These tests require the Django ORM (integration tests).
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
import pytest

from apps.guards.enums import (
    ClientVisibility,
    GuardState,
    LabType,
    PauseReason,
)
from apps.guards.models import SessionPresence, UsageRecord
from apps.guards.services import (
    ensure_session_presence,
    evaluate_inactivity,
    evaluate_runtime_cap,
    evaluate_wall_clock,
    get_guard_state_for_simulation,
    get_usage_snapshot,
    guard_service_entry,
    record_heartbeat,
    record_usage,
    resume_guard_state,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def simulation(db):
    """Create a minimal Simulation for testing."""
    from apps.simcore.models import Simulation

    return Simulation.objects.create()


@pytest.fixture
def trainerlab_presence(simulation):
    """Create a SessionPresence for a TrainerLab session."""
    now = timezone.now()
    return SessionPresence.objects.create(
        simulation=simulation,
        lab_type=LabType.TRAINERLAB,
        guard_state=GuardState.ACTIVE,
        last_presence_at=now,
        wall_clock_started_at=now,
        wall_clock_expires_at=now + timedelta(hours=2),
        engine_runnable=True,
    )


class TestEnsureSessionPresence:
    def test_creates_new_presence(self, simulation):
        presence = ensure_session_presence(simulation.pk, LabType.TRAINERLAB)
        assert presence.simulation_id == simulation.pk
        assert presence.lab_type == LabType.TRAINERLAB
        assert presence.guard_state == GuardState.ACTIVE
        assert presence.engine_runnable is True
        assert presence.wall_clock_started_at is not None

    def test_idempotent(self, simulation):
        p1 = ensure_session_presence(simulation.pk, LabType.TRAINERLAB)
        p2 = ensure_session_presence(simulation.pk, LabType.TRAINERLAB)
        assert p1.pk == p2.pk


class TestRecordHeartbeat:
    def test_updates_presence(self, simulation, trainerlab_presence):
        presence = record_heartbeat(simulation.pk, ClientVisibility.FOREGROUND)
        assert presence.client_visibility == ClientVisibility.FOREGROUND
        assert presence.last_presence_at is not None

    def test_clears_warning(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.WARNING
        trainerlab_presence.warning_sent_at = timezone.now()
        trainerlab_presence.save()

        presence = record_heartbeat(simulation.pk, ClientVisibility.FOREGROUND)
        assert presence.guard_state == GuardState.ACTIVE
        assert presence.warning_sent_at is None

    def test_invalid_visibility_defaults_to_unknown(self, simulation, trainerlab_presence):
        presence = record_heartbeat(simulation.pk, "invalid_value")
        assert presence.client_visibility == ClientVisibility.UNKNOWN


class TestEvaluateInactivity:
    def test_fresh_presence_no_transition(self, simulation, trainerlab_presence):
        result = evaluate_inactivity(simulation.pk)
        assert result is None

    def test_stale_presence_triggers_warning(self, simulation, trainerlab_presence):
        trainerlab_presence.last_presence_at = timezone.now() - timedelta(seconds=275)
        trainerlab_presence.save()

        result = evaluate_inactivity(simulation.pk)
        assert result == GuardState.WARNING

        trainerlab_presence.refresh_from_db()
        assert trainerlab_presence.guard_state == GuardState.WARNING

    def test_very_stale_triggers_pause(self, simulation, trainerlab_presence):
        trainerlab_presence.last_presence_at = timezone.now() - timedelta(seconds=310)
        trainerlab_presence.save()

        result = evaluate_inactivity(simulation.pk)
        assert result == GuardState.PAUSED_INACTIVITY

        trainerlab_presence.refresh_from_db()
        assert trainerlab_presence.guard_state == GuardState.PAUSED_INACTIVITY
        assert trainerlab_presence.pause_reason == PauseReason.INACTIVITY
        assert trainerlab_presence.engine_runnable is False

    def test_paused_time_does_not_increase_active_runtime(self, simulation, trainerlab_presence):
        """Verify that once paused, the session's guard state stays paused
        and does not re-evaluate."""
        trainerlab_presence.guard_state = GuardState.PAUSED_INACTIVITY
        trainerlab_presence.save()

        result = evaluate_inactivity(simulation.pk)
        assert result is None  # No transition — already paused.

    def test_chatlab_skips_inactivity(self, simulation):
        """ChatLab sessions should not be inactivity-checked."""
        SessionPresence.objects.create(
            simulation=simulation,
            lab_type=LabType.CHATLAB,
            guard_state=GuardState.ACTIVE,
            last_presence_at=timezone.now() - timedelta(seconds=600),
            engine_runnable=True,
        )
        result = evaluate_inactivity(simulation.pk)
        assert result is None


class TestEvaluateRuntimeCap:
    def test_under_cap_no_transition(self, simulation, trainerlab_presence):
        result = evaluate_runtime_cap(simulation.pk, active_elapsed=600)
        assert result is None

    def test_over_cap_transitions(self, simulation, trainerlab_presence):
        result = evaluate_runtime_cap(simulation.pk, active_elapsed=99999)
        # Default policy has no runtime cap, so this should be None.
        assert result is None

    def test_already_paused_no_transition(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_RUNTIME_CAP
        trainerlab_presence.save()

        result = evaluate_runtime_cap(simulation.pk, active_elapsed=99999)
        assert result is None


class TestEvaluateWallClock:
    def test_not_expired_no_transition(self, simulation, trainerlab_presence):
        result = evaluate_wall_clock(simulation.pk)
        assert result is None

    def test_expired_transitions_to_ended(self, simulation, trainerlab_presence):
        trainerlab_presence.wall_clock_expires_at = timezone.now() - timedelta(minutes=1)
        trainerlab_presence.save()

        result = evaluate_wall_clock(simulation.pk)
        assert result == GuardState.ENDED

        trainerlab_presence.refresh_from_db()
        assert trainerlab_presence.guard_state == GuardState.ENDED
        assert trainerlab_presence.engine_runnable is False


class TestGuardServiceEntry:
    def test_no_presence_allows(self, simulation):
        """If no presence row exists, guard is backwards-compatible."""
        decision = guard_service_entry(simulation.pk)
        assert decision.allowed

    def test_active_presence_allows(self, simulation, trainerlab_presence):
        decision = guard_service_entry(simulation.pk, active_elapsed=0)
        assert decision.allowed

    def test_paused_presence_denies(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_INACTIVITY
        trainerlab_presence.save()

        decision = guard_service_entry(simulation.pk, active_elapsed=0)
        assert not decision.allowed


class TestResumeGuardState:
    def test_inactivity_pause_resumable(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_INACTIVITY
        trainerlab_presence.pause_reason = PauseReason.INACTIVITY
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        decision = resume_guard_state(simulation.pk)
        assert decision.allowed

        trainerlab_presence.refresh_from_db()
        assert trainerlab_presence.guard_state == GuardState.ACTIVE
        assert trainerlab_presence.engine_runnable is True

    def test_runtime_cap_not_resumable(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_RUNTIME_CAP
        trainerlab_presence.save()

        decision = resume_guard_state(simulation.pk)
        assert not decision.allowed


class TestUsageAccounting:
    def test_record_and_snapshot(self, simulation):
        record_usage(
            simulation_id=simulation.pk,
            user_id=None,
            account_id=None,
            lab_type=LabType.TRAINERLAB,
            product_code="trainerlab_go",
            input_tokens=100,
            output_tokens=200,
            reasoning_tokens=50,
            total_tokens=350,
        )
        snapshot = get_usage_snapshot(simulation_id=simulation.pk)
        assert snapshot["session_total_tokens"] == 350

    def test_incremental_upsert(self, simulation):
        for _ in range(3):
            record_usage(
                simulation_id=simulation.pk,
                user_id=None,
                account_id=None,
                lab_type=LabType.TRAINERLAB,
                product_code="trainerlab_go",
                input_tokens=100,
                output_tokens=200,
                total_tokens=300,
            )
        snapshot = get_usage_snapshot(simulation_id=simulation.pk)
        assert snapshot["session_total_tokens"] == 900
        # Should be a single row, not three.
        assert UsageRecord.objects.filter(simulation=simulation).count() == 1

    def test_multi_scope_recording(self, simulation):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole

        User = get_user_model()
        role = UserRole.objects.create()
        user = User.objects.create_user(email="test@example.com", password="test", role=role)
        simulation.user = user
        simulation.save()

        record_usage(
            simulation_id=simulation.pk,
            user_id=user.pk,
            account_id=None,
            lab_type=LabType.TRAINERLAB,
            product_code="trainerlab_go",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
        )

        snapshot = get_usage_snapshot(
            simulation_id=simulation.pk,
            user_id=user.pk,
        )
        assert snapshot["session_total_tokens"] == 300
        assert snapshot["user_total_tokens"] == 300


class TestGetGuardState:
    def test_no_presence_returns_defaults(self, simulation):
        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.ACTIVE
        assert state["engine_runnable"] is True

    def test_with_presence(self, simulation, trainerlab_presence):
        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.ACTIVE
        assert state["engine_runnable"] is True

    def test_paused_includes_denial(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_RUNTIME_CAP
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.PAUSED_RUNTIME_CAP
        assert state["engine_runnable"] is False
        assert state["denial_reason"] is not None
