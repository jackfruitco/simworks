"""Tests for guard service functions.

These tests require the Django ORM (integration tests).
"""

from __future__ import annotations

from datetime import timedelta
import unittest.mock

from django.utils import timezone
import pytest

from apps.guards.enums import (
    ClientVisibility,
    DenialReason,
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

    def test_very_stale_does_not_overwrite_inactivity_reason(self, simulation, trainerlab_presence):
        """Guard state must stay PAUSED_INACTIVITY with reason=INACTIVITY
        even when the trainerlab session has no matching TrainerSession row
        (integration detail — no TrainerSession in this fixture)."""
        trainerlab_presence.last_presence_at = timezone.now() - timedelta(seconds=310)
        trainerlab_presence.save()

        result = evaluate_inactivity(simulation.pk)
        assert result == GuardState.PAUSED_INACTIVITY

        trainerlab_presence.refresh_from_db()
        # Reason must remain INACTIVITY, not MANUAL
        assert trainerlab_presence.pause_reason == PauseReason.INACTIVITY

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


class TestManualPause:
    """Manual pause should use PAUSED_MANUAL, distinct from PAUSED_INACTIVITY."""

    def test_manual_pause_denies_runtime(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_MANUAL
        trainerlab_presence.pause_reason = PauseReason.MANUAL
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        decision = guard_service_entry(simulation.pk, active_elapsed=0)
        assert not decision.allowed

    def test_manual_pause_is_resumable(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_MANUAL
        trainerlab_presence.pause_reason = PauseReason.MANUAL
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        decision = resume_guard_state(simulation.pk)
        assert decision.allowed

        trainerlab_presence.refresh_from_db()
        assert trainerlab_presence.guard_state == GuardState.ACTIVE
        assert trainerlab_presence.engine_runnable is True

    def test_manual_pause_is_distinct_from_inactivity(self, simulation, trainerlab_presence):
        """PAUSED_MANUAL and PAUSED_INACTIVITY are different guard states."""
        assert GuardState.PAUSED_MANUAL != GuardState.PAUSED_INACTIVITY


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


class TestUsageUniqueness:
    """UsageRecord upsert must not create duplicate rows under any conditions."""

    def test_repeated_calls_produce_single_row(self, simulation):
        for _ in range(5):
            record_usage(
                simulation_id=simulation.pk,
                user_id=None,
                account_id=None,
                lab_type=LabType.TRAINERLAB,
                product_code="trainerlab_go",
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
            )
        assert UsageRecord.objects.filter(simulation=simulation).count() == 1
        snapshot = get_usage_snapshot(simulation_id=simulation.pk)
        assert snapshot["session_total_tokens"] == 150

    def test_different_periods_produce_separate_rows(self, simulation):
        from django.utils import timezone as tz

        from apps.guards.services import _upsert_usage

        now = tz.now()
        period_a = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Simulate a different month by replacing month.
        if now.month == 1:
            period_b = period_a.replace(month=2)
        else:
            period_b = period_a.replace(month=now.month - 1)

        for period in (period_a, period_b):
            _upsert_usage(
                scope_type="session",
                simulation_id=simulation.pk,
                user_id=None,
                account_id=None,
                lab_type=LabType.TRAINERLAB,
                product_code="trainerlab_go",
                period_start=period,
                input_tokens=100,
                output_tokens=200,
                reasoning_tokens=0,
                total_tokens=300,
            )
        assert UsageRecord.objects.filter(simulation=simulation).count() == 2


class TestTokenLimitBehavior:
    """Token limits are optional — when None, no enforcement occurs."""

    def test_no_limits_configured_always_allows(self, simulation, trainerlab_presence):
        """Default policy has no token limits — guard must allow."""
        decision = guard_service_entry(simulation.pk, active_elapsed=0)
        assert decision.allowed

    def test_session_limit_enforced_when_configured(self, simulation, trainerlab_presence):
        from apps.guards.decisions import RuntimeGuard
        from apps.guards.policy import GuardPolicy

        policy = GuardPolicy(session_token_limit=1000)
        guard = RuntimeGuard(trainerlab_presence, policy)
        snapshot = {"session_total_tokens": 1000}
        decision = guard.check_usage_limits(snapshot)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.SESSION_TOKEN_LIMIT

    def test_no_limits_means_unlimited(self, simulation, trainerlab_presence):
        from apps.guards.decisions import RuntimeGuard
        from apps.guards.policy import GuardPolicy

        policy = GuardPolicy()  # All limits None
        guard = RuntimeGuard(trainerlab_presence, policy)
        snapshot = {"session_total_tokens": 999_999_999}
        decision = guard.check_usage_limits(snapshot)
        assert decision.allowed


class TestGetGuardState:
    def test_no_presence_returns_defaults(self, simulation):
        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.ACTIVE
        assert state["engine_runnable"] is True
        assert state["warnings"] == []
        assert state["denial"] is None

    def test_with_presence(self, simulation, trainerlab_presence):
        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.ACTIVE
        assert state["engine_runnable"] is True
        assert state["denial"] is None

    def test_paused_runtime_cap_has_structured_denial(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_RUNTIME_CAP
        trainerlab_presence.pause_reason = PauseReason.RUNTIME_CAP
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.PAUSED_RUNTIME_CAP
        assert state["engine_runnable"] is False
        denial = state["denial"]
        assert denial is not None
        assert denial["code"] == "runtime_cap_reached"
        assert denial["severity"] == "error"
        assert denial["resumable"] is False
        assert denial["terminal"] is True

    def test_paused_inactivity_has_resumable_denial(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_INACTIVITY
        trainerlab_presence.pause_reason = PauseReason.INACTIVITY
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        denial = state["denial"]
        assert denial is not None
        assert denial["code"] == "session_paused"
        assert denial["resumable"] is True
        assert denial["terminal"] is False

    def test_inactivity_warning_is_structured(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.WARNING
        trainerlab_presence.last_presence_at = timezone.now() - timedelta(seconds=275)
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        assert len(state["warnings"]) >= 1
        warning = state["warnings"][0]
        assert warning["code"] == "inactivity_warning"
        assert warning["severity"] == "warning"
        assert warning["expires_in_seconds"] is not None

    def test_locked_usage_uses_canonical_code(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.LOCKED_USAGE
        trainerlab_presence.pause_reason = PauseReason.USAGE_LIMIT
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        denial = state["denial"]
        assert denial is not None
        assert denial["code"] == DenialReason.USAGE_LIMIT_REACHED
        assert denial["resumable"] is True
        assert denial["terminal"] is False

    def test_ended_uses_session_ended_code(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.ENDED
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        denial = state["denial"]
        assert denial is not None
        assert denial["code"] == DenialReason.SESSION_ENDED
        assert denial["resumable"] is False
        assert denial["terminal"] is True

    def test_no_denial_reason_or_denial_message_keys(self, simulation, trainerlab_presence):
        """Verify the old flat denial fields are removed."""
        state = get_guard_state_for_simulation(simulation.pk)
        assert "denial_reason" not in state
        assert "denial_message" not in state

    def test_no_presence_guard_reason_is_none(self, simulation):
        """Default state should have guard_reason='none'."""
        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_reason"] == "none"
        assert "pause_reason" not in state

    def test_guard_reason_replaces_pause_reason(self, simulation, trainerlab_presence):
        """Public response uses guard_reason, not pause_reason."""
        trainerlab_presence.guard_state = GuardState.PAUSED_INACTIVITY
        trainerlab_presence.pause_reason = PauseReason.INACTIVITY
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_reason"] == PauseReason.INACTIVITY
        assert "pause_reason" not in state

    def test_ended_wall_clock_guard_reason(self, simulation, trainerlab_presence):
        """Ended by wall-clock uses guard_reason=wall_clock_expiry, denial.code=session_ended."""
        trainerlab_presence.guard_state = GuardState.ENDED
        trainerlab_presence.pause_reason = PauseReason.WALL_CLOCK_EXPIRY
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        assert state["guard_state"] == GuardState.ENDED
        assert state["guard_reason"] == PauseReason.WALL_CLOCK_EXPIRY

        denial = state["denial"]
        assert denial is not None
        assert denial["code"] == DenialReason.SESSION_ENDED
        assert denial["terminal"] is True
        assert denial["metadata"]["guard_reason"] == PauseReason.WALL_CLOCK_EXPIRY

    def test_denial_metadata_uses_guard_reason(self, simulation, trainerlab_presence):
        """Denial metadata should use guard_reason, not pause_reason."""
        trainerlab_presence.guard_state = GuardState.LOCKED_USAGE
        trainerlab_presence.pause_reason = PauseReason.USAGE_LIMIT
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        state = get_guard_state_for_simulation(simulation.pk)
        denial = state["denial"]
        assert "guard_reason" in denial["metadata"]
        assert "pause_reason" not in denial["metadata"]
        assert denial["metadata"]["guard_reason"] == PauseReason.USAGE_LIMIT


class TestGuardEventPayloadNaming:
    """Guard event payloads must use ``guard_reason``, not ``pause_reason``."""

    def test_inactivity_event_uses_guard_reason(self, simulation, trainerlab_presence):
        trainerlab_presence.last_presence_at = timezone.now() - timedelta(seconds=310)
        trainerlab_presence.save()

        with unittest.mock.patch("apps.guards.services._emit_guard_event") as mock_emit:
            evaluate_inactivity(simulation.pk)

        mock_emit.assert_called_once()
        payload = mock_emit.call_args[0][2]
        assert payload["guard_state"] == GuardState.PAUSED_INACTIVITY
        assert payload["guard_reason"] == PauseReason.INACTIVITY
        assert "pause_reason" not in payload

    def test_wall_clock_ended_event_uses_guard_reason(self, simulation, trainerlab_presence):
        trainerlab_presence.wall_clock_expires_at = timezone.now() - timedelta(minutes=1)
        trainerlab_presence.save()

        with unittest.mock.patch("apps.guards.services._emit_guard_event") as mock_emit:
            evaluate_wall_clock(simulation.pk)

        mock_emit.assert_called_once()
        payload = mock_emit.call_args[0][2]
        assert payload["guard_state"] == GuardState.ENDED
        assert payload["guard_reason"] == PauseReason.WALL_CLOCK_EXPIRY
        assert "pause_reason" not in payload

    def test_resume_event_uses_guard_reason(self, simulation, trainerlab_presence):
        trainerlab_presence.guard_state = GuardState.PAUSED_INACTIVITY
        trainerlab_presence.pause_reason = PauseReason.INACTIVITY
        trainerlab_presence.engine_runnable = False
        trainerlab_presence.save()

        with unittest.mock.patch("apps.guards.services._emit_guard_event") as mock_emit:
            resume_guard_state(simulation.pk)

        mock_emit.assert_called_once()
        payload = mock_emit.call_args[0][2]
        assert payload["guard_state"] == GuardState.ACTIVE
        assert payload["guard_reason"] == PauseReason.NONE
        assert "pause_reason" not in payload
