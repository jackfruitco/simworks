"""Tests for the guard presentation layer.

Validates that:
- signal builders produce correct shapes
- canonical denial codes come from DenialReason (single source of truth)
- same guard state always produces the same code, resumable, terminal
- guard-state endpoint and 403 denial path agree on semantics
"""

from __future__ import annotations

from apps.guards.enums import DenialReason, GuardState, PauseReason
from apps.guards.presentation import (
    build_denial_signal,
    build_warning_signal,
    denial_for_state,
    warning_approaching_runtime_cap,
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
    """Canonical denial mapping uses DenialReason enum values."""

    def test_paused_inactivity(self):
        sig = denial_for_state(GuardState.PAUSED_INACTIVITY, PauseReason.INACTIVITY)
        assert sig is not None
        assert sig["code"] == DenialReason.SESSION_PAUSED
        assert sig["resumable"] is True
        assert sig["terminal"] is False
        assert sig["severity"] == "error"
        assert sig["metadata"]["guard_state"] == GuardState.PAUSED_INACTIVITY
        assert sig["metadata"]["guard_reason"] == PauseReason.INACTIVITY
        assert "pause_reason" not in sig["metadata"]

    def test_paused_manual(self):
        sig = denial_for_state(GuardState.PAUSED_MANUAL, PauseReason.MANUAL)
        assert sig is not None
        assert sig["code"] == DenialReason.SESSION_PAUSED
        assert sig["resumable"] is True
        assert sig["terminal"] is False

    def test_paused_runtime_cap(self):
        sig = denial_for_state(GuardState.PAUSED_RUNTIME_CAP, PauseReason.RUNTIME_CAP)
        assert sig is not None
        assert sig["code"] == DenialReason.RUNTIME_CAP_REACHED
        assert sig["resumable"] is False
        assert sig["terminal"] is True

    def test_locked_usage(self):
        sig = denial_for_state(GuardState.LOCKED_USAGE, PauseReason.USAGE_LIMIT)
        assert sig is not None
        assert sig["code"] == DenialReason.USAGE_LIMIT_REACHED
        assert sig["resumable"] is True
        assert sig["terminal"] is False

    def test_ended(self):
        sig = denial_for_state(GuardState.ENDED)
        assert sig is not None
        assert sig["code"] == DenialReason.SESSION_ENDED
        assert sig["resumable"] is False
        assert sig["terminal"] is True

    def test_ended_wall_clock(self):
        sig = denial_for_state(GuardState.ENDED, PauseReason.WALL_CLOCK_EXPIRY)
        assert sig is not None
        assert sig["code"] == DenialReason.SESSION_ENDED
        assert sig["metadata"]["guard_state"] == GuardState.ENDED
        assert sig["metadata"]["guard_reason"] == PauseReason.WALL_CLOCK_EXPIRY
        assert sig["terminal"] is True

    def test_active_returns_none(self):
        assert denial_for_state(GuardState.ACTIVE) is None

    def test_warning_returns_none(self):
        assert denial_for_state(GuardState.WARNING) is None


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


class TestDenialFromReason:
    """denial_from_reason produces fully-specified signals for known codes."""

    def test_usage_limit_reached(self):
        from apps.guards.presentation import denial_from_reason

        sig = denial_from_reason(DenialReason.USAGE_LIMIT_REACHED, "Sending is locked.")
        assert sig["code"] == DenialReason.USAGE_LIMIT_REACHED
        assert sig["severity"] == "error"
        assert sig["title"] == "Usage limit reached"
        assert sig["resumable"] is True
        assert sig["terminal"] is False

    def test_insufficient_token_budget(self):
        from apps.guards.presentation import denial_from_reason

        sig = denial_from_reason(DenialReason.INSUFFICIENT_TOKEN_BUDGET, "Not enough tokens.")
        assert sig["code"] == DenialReason.INSUFFICIENT_TOKEN_BUDGET
        assert sig["title"] == "Insufficient token budget"
        assert sig["resumable"] is False
        assert sig["terminal"] is False

    def test_unknown_reason_falls_back_gracefully(self):
        from apps.guards.presentation import denial_from_reason

        sig = denial_from_reason("unknown_reason", "Something happened.")
        assert sig["code"] == "unknown_reason"
        assert sig["title"] == "Action denied"
        assert sig["message"] == "Something happened."

    def test_all_denial_reasons_are_covered(self):
        """Every DenialReason should have an entry in _REASON_SIGNAL_MAP."""
        from apps.guards.presentation import _REASON_SIGNAL_MAP

        for reason in DenialReason:
            assert reason.value in _REASON_SIGNAL_MAP, (
                f"DenialReason.{reason.name} ({reason.value!r}) is missing from _REASON_SIGNAL_MAP"
            )


class TestCodeConsistency:
    """All denial codes from presentation.py must be DenialReason values."""

    def test_all_denial_map_codes_are_denial_reason_values(self):
        from apps.guards.presentation import _DENIAL_MAP

        valid_codes = {v.value for v in DenialReason}
        for state, entry in _DENIAL_MAP.items():
            assert entry["code"] in valid_codes, (
                f"Denial map for {state} uses code {entry['code']!r} "
                f"which is not a DenialReason value"
            )

    def test_decisions_and_presentation_use_same_codes(self):
        """_deny_for_current_state() and denial_for_state() should produce
        the same code for each non-runnable guard state."""
        from apps.guards.decisions import RuntimeGuard
        from apps.guards.enums import NON_RUNNABLE_STATES
        from apps.guards.models import SessionPresence
        from apps.guards.policy import GuardPolicy

        policy = GuardPolicy()
        for state in NON_RUNNABLE_STATES:
            # Decision layer
            presence = SessionPresence(
                lab_type="trainerlab",
                guard_state=state,
                pause_reason="none",
                engine_runnable=False,
            )
            guard = RuntimeGuard(presence, policy)
            decision = guard._deny_for_current_state()

            # Presentation layer
            signal = denial_for_state(state)

            assert signal is not None, f"denial_for_state returned None for {state}"
            assert decision.denial_reason == signal["code"], (
                f"Code mismatch for state {state}: "
                f"decisions={decision.denial_reason!r}, "
                f"presentation={signal['code']!r}"
            )
