"""Tests for the RuntimeGuard decision layer."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.guards.decisions import GuardDecision, RuntimeGuard
from apps.guards.enums import (
    ClientVisibility,
    DenialReason,
    GuardState,
    LabType,
    PauseReason,
)
from apps.guards.models import SessionPresence
from apps.guards.policy import GuardPolicy


def _make_presence(**overrides) -> SessionPresence:
    """Build an unsaved SessionPresence for testing."""
    defaults = {
        "lab_type": LabType.TRAINERLAB,
        "guard_state": GuardState.ACTIVE,
        "pause_reason": PauseReason.NONE,
        "engine_runnable": True,
        "client_visibility": ClientVisibility.FOREGROUND,
    }
    defaults.update(overrides)
    return SessionPresence(**defaults)


class TestGuardDecisionFactory:
    def test_allow(self):
        d = GuardDecision.allow()
        assert d.allowed is True
        assert d.denial_reason == ""

    def test_allow_with_warnings(self):
        d = GuardDecision.allow(["low budget"])
        assert d.allowed is True
        assert "low budget" in d.warnings

    def test_deny(self):
        d = GuardDecision.deny("reason", "message")
        assert d.allowed is False
        assert d.denial_reason == "reason"
        assert d.denial_message == "message"


class TestMayStartRuntimeOperation:
    """Guard should allow/deny new runtime calls based on state."""

    def test_active_session_allowed(self):
        presence = _make_presence()
        policy = GuardPolicy(runtime_cap_seconds=1200)
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=600)
        assert decision.allowed

    def test_paused_inactivity_denied(self):
        presence = _make_presence(guard_state=GuardState.PAUSED_INACTIVITY)
        policy = GuardPolicy()
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=0)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.SESSION_PAUSED

    def test_paused_runtime_cap_denied(self):
        presence = _make_presence(guard_state=GuardState.PAUSED_RUNTIME_CAP)
        policy = GuardPolicy()
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=0)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.RUNTIME_CAP_REACHED

    def test_locked_usage_denied(self):
        presence = _make_presence(guard_state=GuardState.LOCKED_USAGE)
        policy = GuardPolicy()
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=0)
        assert not decision.allowed

    def test_runtime_cap_exceeded(self):
        presence = _make_presence()
        policy = GuardPolicy(runtime_cap_seconds=1200)
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=1200)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.RUNTIME_CAP_REACHED

    def test_no_runtime_cap_unlimited(self):
        presence = _make_presence()
        policy = GuardPolicy(runtime_cap_seconds=None)
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=999999)
        assert decision.allowed

    def test_wall_clock_expired(self):
        past = timezone.now() - timedelta(hours=1)
        presence = _make_presence(wall_clock_expires_at=past)
        policy = GuardPolicy()
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=0)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.WALL_CLOCK_EXPIRED

    def test_near_cap_includes_warning(self):
        presence = _make_presence()
        policy = GuardPolicy(runtime_cap_seconds=1200)
        guard = RuntimeGuard(presence, policy)
        decision = guard.may_start_runtime_operation(active_elapsed=1000)
        assert decision.allowed
        assert any("200 seconds" in w for w in decision.warnings)


class TestInactivity:
    """Inactivity warning and pause decisions."""

    def test_fresh_heartbeat_no_warning(self):
        presence = _make_presence()
        policy = GuardPolicy(inactivity_warning_seconds=270, inactivity_pause_seconds=300)
        guard = RuntimeGuard(presence, policy)
        assert guard.should_warn(60).allowed

    def test_stale_heartbeat_triggers_warning(self):
        presence = _make_presence()
        policy = GuardPolicy(inactivity_warning_seconds=270, inactivity_pause_seconds=300)
        guard = RuntimeGuard(presence, policy)
        decision = guard.should_warn(275)
        assert not decision.allowed

    def test_very_stale_triggers_pause(self):
        presence = _make_presence()
        policy = GuardPolicy(inactivity_warning_seconds=270, inactivity_pause_seconds=300)
        guard = RuntimeGuard(presence, policy)
        decision = guard.should_pause(305)
        assert not decision.allowed

    def test_disabled_inactivity_never_warns(self):
        """ChatLab disables inactivity by setting thresholds to 0."""
        presence = _make_presence()
        policy = GuardPolicy(inactivity_warning_seconds=0, inactivity_pause_seconds=0)
        guard = RuntimeGuard(presence, policy)
        assert guard.should_warn(9999).allowed
        assert guard.should_pause(9999).allowed


class TestMayResumeSession:
    """Resume logic: inactivity-paused is resumable, runtime-cap is not."""

    def test_inactivity_pause_resumable(self):
        presence = _make_presence(guard_state=GuardState.PAUSED_INACTIVITY)
        guard = RuntimeGuard(presence, GuardPolicy())
        assert guard.may_resume_session().allowed

    def test_runtime_cap_pause_not_resumable(self):
        presence = _make_presence(guard_state=GuardState.PAUSED_RUNTIME_CAP)
        guard = RuntimeGuard(presence, GuardPolicy())
        decision = guard.may_resume_session()
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.RUNTIME_CAP_REACHED

    def test_ended_not_resumable(self):
        presence = _make_presence(guard_state=GuardState.ENDED)
        guard = RuntimeGuard(presence, GuardPolicy())
        assert not guard.may_resume_session().allowed

    def test_active_session_resume_allowed(self):
        presence = _make_presence(guard_state=GuardState.ACTIVE)
        guard = RuntimeGuard(presence, GuardPolicy())
        assert guard.may_resume_session().allowed


class TestMayStartSession:
    """Pre-session admission checks (token budget)."""

    def test_sufficient_budget_allowed(self):
        presence = _make_presence(lab_type=LabType.TRAINERLAB)
        policy = GuardPolicy(
            pre_session_init_reserve_tokens=50_000,
            pre_session_safety_reserve_tokens=10_000,
        )
        guard = RuntimeGuard(presence, policy)
        snapshot = {"user_total_tokens": 0, "account_total_tokens": 0}
        assert guard.may_start_session(snapshot).allowed

    def test_insufficient_budget_denied(self):
        presence = _make_presence(lab_type=LabType.TRAINERLAB)
        policy = GuardPolicy(
            pre_session_init_reserve_tokens=50_000,
            pre_session_safety_reserve_tokens=10_000,
            user_token_limit=100_000,
        )
        guard = RuntimeGuard(presence, policy)
        # User has used 95k of 100k limit → 5k remaining < 60k reserve
        snapshot = {"user_total_tokens": 95_000, "account_total_tokens": 0}
        decision = guard.may_start_session(snapshot)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.INSUFFICIENT_TOKEN_BUDGET

    def test_chatlab_skips_budget_check(self):
        """ChatLab does not have a pre-session admission check."""
        presence = _make_presence(lab_type=LabType.CHATLAB)
        policy = GuardPolicy(user_token_limit=100)
        guard = RuntimeGuard(presence, policy)
        snapshot = {"user_total_tokens": 99}
        assert guard.may_start_session(snapshot).allowed


class TestShouldLockSend:
    """ChatLab send-lock decisions."""

    def test_plenty_of_budget_allowed(self):
        presence = _make_presence(lab_type=LabType.CHATLAB)
        policy = GuardPolicy(
            chat_send_min_safe_tokens=5_000,
            chat_warning_threshold_tokens=20_000,
            user_token_limit=1_000_000,
        )
        guard = RuntimeGuard(presence, policy)
        snapshot = {"user_total_tokens": 0}
        decision = guard.should_lock_send(snapshot)
        assert decision.allowed
        assert len(decision.warnings) == 0

    def test_near_limit_warns(self):
        presence = _make_presence(lab_type=LabType.CHATLAB)
        policy = GuardPolicy(
            chat_send_min_safe_tokens=5_000,
            chat_warning_threshold_tokens=20_000,
            user_token_limit=100_000,
        )
        guard = RuntimeGuard(presence, policy)
        snapshot = {"user_total_tokens": 90_000}  # 10k remaining
        decision = guard.should_lock_send(snapshot)
        assert decision.allowed
        assert len(decision.warnings) > 0
        assert "remaining" in decision.warnings[0].lower()

    def test_below_safe_threshold_locks(self):
        presence = _make_presence(lab_type=LabType.CHATLAB)
        policy = GuardPolicy(
            chat_send_min_safe_tokens=5_000,
            user_token_limit=100_000,
        )
        guard = RuntimeGuard(presence, policy)
        snapshot = {"user_total_tokens": 97_000}  # 3k remaining < 5k
        decision = guard.should_lock_send(snapshot)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.CHAT_SEND_LOCKED

    def test_paused_session_locks_send(self):
        presence = _make_presence(guard_state=GuardState.PAUSED_RUNTIME_CAP)
        policy = GuardPolicy()
        guard = RuntimeGuard(presence, policy)
        decision = guard.should_lock_send({})
        assert not decision.allowed

    def test_no_limits_configured_allows(self):
        presence = _make_presence(lab_type=LabType.CHATLAB)
        policy = GuardPolicy()  # No token limits
        guard = RuntimeGuard(presence, policy)
        decision = guard.should_lock_send({})
        assert decision.allowed


class TestUsageLimits:
    """Usage limit precedence checks."""

    def test_session_limit_exceeded(self):
        presence = _make_presence()
        policy = GuardPolicy(session_token_limit=10_000)
        guard = RuntimeGuard(presence, policy)
        snapshot = {"session_total_tokens": 10_000}
        decision = guard.check_usage_limits(snapshot)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.SESSION_TOKEN_LIMIT

    def test_user_limit_exceeded(self):
        presence = _make_presence()
        policy = GuardPolicy(user_token_limit=50_000)
        guard = RuntimeGuard(presence, policy)
        snapshot = {"session_total_tokens": 0, "user_total_tokens": 50_000}
        decision = guard.check_usage_limits(snapshot)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.USER_TOKEN_LIMIT

    def test_account_limit_exceeded(self):
        presence = _make_presence()
        policy = GuardPolicy(account_token_limit=100_000)
        guard = RuntimeGuard(presence, policy)
        snapshot = {
            "session_total_tokens": 0,
            "user_total_tokens": 0,
            "account_total_tokens": 100_000,
        }
        decision = guard.check_usage_limits(snapshot)
        assert not decision.allowed
        assert decision.denial_reason == DenialReason.ACCOUNT_TOKEN_LIMIT

    def test_session_limit_takes_precedence(self):
        """Session limit should be reported before user/account."""
        presence = _make_presence()
        policy = GuardPolicy(
            session_token_limit=10,
            user_token_limit=10,
            account_token_limit=10,
        )
        guard = RuntimeGuard(presence, policy)
        snapshot = {
            "session_total_tokens": 10,
            "user_total_tokens": 10,
            "account_total_tokens": 10,
        }
        decision = guard.check_usage_limits(snapshot)
        assert decision.denial_reason == DenialReason.SESSION_TOKEN_LIMIT

    def test_no_limits_allows(self):
        presence = _make_presence()
        policy = GuardPolicy()
        guard = RuntimeGuard(presence, policy)
        snapshot = {"session_total_tokens": 999999}
        assert guard.check_usage_limits(snapshot).allowed
