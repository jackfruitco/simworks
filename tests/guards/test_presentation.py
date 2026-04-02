"""Tests for the guard presentation layer."""

from __future__ import annotations

from apps.guards.enums import GuardState, PauseReason
from apps.guards.presentation import (
    build_denial_signal,
    build_warning_signal,
    denial_for_state,
    denial_from_decision,
    warning_approaching_runtime_cap,
    warning_approaching_usage_limit,
    warning_inactivity,
)

pytestmark = []

# ── Signal shape keys ──────────────────────────────────────────────────

SIGNAL_KEYS = {
    "code",
    "severity",
    "title",
    "message",
    "resumable",
    "terminal",
    "expires_in_seconds",
    "metadata",
}


class TestBuildWarningSignal:
    def test_shape(self):
        sig = build_warning_signal(code="test", message="hello")
        assert set(sig.keys()) == SIGNAL_KEYS
        assert sig["severity"] == "warning"
        assert sig["code"] == "test"
        assert sig["message"] == "hello"
        assert sig["resumable"] is None
        assert sig["terminal"] is None

    def test_with_metadata(self):
        sig = build_warning_signal(
            code="x", message="m", title="T", expires_in_seconds=60, metadata={"k": 1}
        )
        assert sig["title"] == "T"
        assert sig["expires_in_seconds"] == 60
        assert sig["metadata"] == {"k": 1}


class TestBuildDenialSignal:
    def test_shape(self):
        sig = build_denial_signal(code="denied", message="no")
        assert set(sig.keys()) == SIGNAL_KEYS
        assert sig["severity"] == "error"
        assert sig["code"] == "denied"
        assert sig["resumable"] is None
        assert sig["terminal"] is None

    def test_with_semantics(self):
        sig = build_denial_signal(code="cap", message="done", resumable=False, terminal=True)
        assert sig["resumable"] is False
        assert sig["terminal"] is True


class TestDenialForState:
    def test_paused_inactivity(self):
        sig = denial_for_state(GuardState.PAUSED_INACTIVITY, PauseReason.INACTIVITY)
        assert sig is not None
        assert sig["code"] == "session_paused"
        assert sig["resumable"] is True
        assert sig["terminal"] is False
        assert sig["severity"] == "error"
        assert sig["metadata"]["guard_state"] == GuardState.PAUSED_INACTIVITY

    def test_paused_manual(self):
        sig = denial_for_state(GuardState.PAUSED_MANUAL, PauseReason.MANUAL)
        assert sig is not None
        assert sig["code"] == "session_paused"
        assert sig["resumable"] is True
        assert sig["terminal"] is False

    def test_paused_runtime_cap(self):
        sig = denial_for_state(GuardState.PAUSED_RUNTIME_CAP, PauseReason.RUNTIME_CAP)
        assert sig is not None
        assert sig["code"] == "runtime_cap_reached"
        assert sig["resumable"] is False
        assert sig["terminal"] is True

    def test_locked_usage(self):
        sig = denial_for_state(GuardState.LOCKED_USAGE, PauseReason.USAGE_LIMIT)
        assert sig is not None
        assert sig["code"] == "usage_limit_reached"
        assert sig["resumable"] is True
        assert sig["terminal"] is False

    def test_ended(self):
        sig = denial_for_state(GuardState.ENDED)
        assert sig is not None
        assert sig["code"] == "session_ended"
        assert sig["resumable"] is False
        assert sig["terminal"] is True

    def test_active_returns_none(self):
        assert denial_for_state(GuardState.ACTIVE) is None

    def test_warning_returns_none(self):
        assert denial_for_state(GuardState.WARNING) is None


class TestDenialFromDecision:
    def test_with_known_state(self):
        sig = denial_from_decision(
            denial_reason="session_paused",
            denial_message="paused",
            guard_state=GuardState.PAUSED_INACTIVITY,
            pause_reason=PauseReason.INACTIVITY,
        )
        # Should use the canonical state-based signal
        assert sig["code"] == "session_paused"
        assert sig["resumable"] is True

    def test_without_state_falls_back(self):
        sig = denial_from_decision(
            denial_reason="chat_send_locked",
            denial_message="Locked.",
        )
        assert sig["code"] == "chat_send_locked"
        assert sig["severity"] == "error"
        assert sig["message"] == "Locked."


class TestWarningApproachingRuntimeCap:
    def test_shape_and_content(self):
        sig = warning_approaching_runtime_cap(120, 1200)
        assert sig["code"] == "approaching_runtime_cap"
        assert sig["severity"] == "warning"
        assert sig["expires_in_seconds"] == 120
        assert sig["metadata"]["remaining_seconds"] == 120
        assert sig["metadata"]["cap_seconds"] == 1200
        assert "120" in sig["message"]


class TestWarningInactivity:
    def test_shape_and_content(self):
        sig = warning_inactivity(30)
        assert sig["code"] == "inactivity_warning"
        assert sig["severity"] == "warning"
        assert sig["expires_in_seconds"] == 30
        assert sig["metadata"]["seconds_until_pause"] == 30


class TestWarningApproachingUsageLimit:
    def test_shape_and_content(self):
        sig = warning_approaching_usage_limit(3, 15000)
        assert sig["code"] == "approaching_usage_limit"
        assert sig["severity"] == "warning"
        assert sig["metadata"]["estimated_turns"] == 3
        assert sig["metadata"]["remaining_tokens"] == 15000
        assert "3" in sig["message"]
