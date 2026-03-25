"""Guard decision layer.

``RuntimeGuard`` is a stateless decision-maker.  It takes presence state,
policy, and usage data and returns structured ``GuardDecision`` objects.

All guard decisions are made here — not in views, services, or templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from .enums import (
    DenialReason,
    GuardState,
    LabType,
    NON_RUNNABLE_STATES,
    PauseReason,
    RESUMABLE_GUARD_STATES,
)
from .models import SessionPresence
from .policy import GuardPolicy


@dataclass(frozen=True)
class GuardDecision:
    """Structured result of a guard check.

    ``allowed=True`` means the caller may proceed.
    ``allowed=False`` means the request must be denied, and ``denial_reason``
    + ``denial_message`` explain why.
    ``warnings`` carries advisory messages the UI may display even when
    the action is allowed (e.g. "5 minutes remaining").
    """

    allowed: bool
    denial_reason: str = ""
    denial_message: str = ""
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def allow(warnings: list[str] | None = None) -> GuardDecision:
        return GuardDecision(allowed=True, warnings=warnings or [])

    @staticmethod
    def deny(reason: str, message: str) -> GuardDecision:
        return GuardDecision(allowed=False, denial_reason=reason, denial_message=message)


class RuntimeGuard:
    """Stateless guard that answers policy questions for a session.

    Instantiate with the current ``SessionPresence`` and resolved
    ``GuardPolicy``, then call the individual check methods.
    """

    def __init__(self, presence: SessionPresence, policy: GuardPolicy) -> None:
        self.presence = presence
        self.policy = policy

    # ── Session lifecycle ───────────────────────────────────────────────

    def may_start_session(self, usage_snapshot: dict) -> GuardDecision:
        """Pre-session admission check.

        For TrainerLab: verifies that the user/account has enough token
        budget for initial scenario generation + safety reserve.
        """
        if self.presence.lab_type == LabType.TRAINERLAB:
            required = self.policy.pre_session_total_reserve
            remaining = self._remaining_budget(usage_snapshot)
            if remaining is not None and remaining < required:
                return GuardDecision.deny(
                    DenialReason.INSUFFICIENT_TOKEN_BUDGET,
                    f"Insufficient token budget to start session. "
                    f"Need {required:,} tokens; {remaining:,} remaining.",
                )
        return GuardDecision.allow()

    def may_resume_session(self) -> GuardDecision:
        """Check if a paused session may be resumed."""
        state = self.presence.guard_state
        if state not in RESUMABLE_GUARD_STATES:
            if state in NON_RUNNABLE_STATES:
                return GuardDecision.deny(
                    DenialReason.RUNTIME_CAP_REACHED,
                    "Session cannot be resumed — runtime cap or terminal state reached.",
                )
        return GuardDecision.allow()

    # ── Runtime operation gating ────────────────────────────────────────

    def may_start_runtime_operation(self, active_elapsed: int) -> GuardDecision:
        """Single entrypoint check before any Orca / AI / runtime call.

        Returns denial if the session is paused, runtime-capped, or
        usage-locked.
        """
        # Check guard state first.
        if self.presence.guard_state in NON_RUNNABLE_STATES:
            return self._deny_for_current_state()

        # Check runtime cap.
        cap_decision = self.check_runtime_cap(active_elapsed)
        if not cap_decision.allowed:
            return cap_decision

        # Check wall clock.
        wc_decision = self.check_wall_clock()
        if not wc_decision.allowed:
            return wc_decision

        # Collect warnings.
        warnings: list[str] = []
        if self.policy.has_runtime_cap:
            remaining = self.policy.runtime_cap_seconds - active_elapsed
            if remaining <= 300:
                warnings.append(f"{remaining} seconds of active runtime remaining.")

        return GuardDecision.allow(warnings)

    # ── Inactivity evaluation ───────────────────────────────────────────

    def should_warn(self, last_presence_age_seconds: float) -> GuardDecision:
        """Should the session enter the WARNING state?"""
        threshold = self.policy.inactivity_warning_seconds
        if threshold <= 0:
            return GuardDecision.allow()
        if last_presence_age_seconds >= threshold:
            remaining_until_pause = max(
                0, self.policy.inactivity_pause_seconds - last_presence_age_seconds
            )
            return GuardDecision.deny(
                DenialReason.SESSION_PAUSED,
                f"Inactivity warning — session will pause in {int(remaining_until_pause)}s.",
            )
        return GuardDecision.allow()

    def should_pause(self, last_presence_age_seconds: float) -> GuardDecision:
        """Should the session be auto-paused due to inactivity?"""
        threshold = self.policy.inactivity_pause_seconds
        if threshold <= 0:
            return GuardDecision.allow()
        if last_presence_age_seconds >= threshold:
            return GuardDecision.deny(
                DenialReason.SESSION_PAUSED,
                "Session paused due to inactivity.",
            )
        return GuardDecision.allow()

    # ── ChatLab send-lock ───────────────────────────────────────────────

    def should_lock_send(self, usage_snapshot: dict) -> GuardDecision:
        """Should ChatLab lock the send button?"""
        if self.presence.guard_state in NON_RUNNABLE_STATES:
            return self._deny_for_current_state()

        remaining = self._remaining_budget(usage_snapshot)
        if remaining is not None:
            if remaining < self.policy.chat_send_min_safe_tokens:
                return GuardDecision.deny(
                    DenialReason.CHAT_SEND_LOCKED,
                    "Usage limit approaching — sending is locked.",
                )
            warnings = []
            if remaining < self.policy.chat_warning_threshold_tokens:
                estimated_turns = max(1, remaining // self.policy.chat_send_min_safe_tokens)
                warnings.append(
                    f"Nearing usage limit — approximately {estimated_turns} "
                    f"message(s) remaining."
                )
            return GuardDecision.allow(warnings)

        return GuardDecision.allow()

    # ── Cap / expiry checks ─────────────────────────────────────────────

    def check_runtime_cap(self, active_elapsed: int) -> GuardDecision:
        """Check if active runtime has exceeded the plan cap."""
        if not self.policy.has_runtime_cap:
            return GuardDecision.allow()
        if active_elapsed >= self.policy.runtime_cap_seconds:
            return GuardDecision.deny(
                DenialReason.RUNTIME_CAP_REACHED,
                f"Active runtime cap of {self.policy.runtime_cap_seconds}s reached.",
            )
        return GuardDecision.allow()

    def check_wall_clock(self, now: datetime | None = None) -> GuardDecision:
        """Check if wall-clock expiry has been reached."""
        if not self.presence.wall_clock_expires_at:
            return GuardDecision.allow()
        now = now or timezone.now()
        if now >= self.presence.wall_clock_expires_at:
            return GuardDecision.deny(
                DenialReason.WALL_CLOCK_EXPIRED,
                "Session wall-clock time has expired.",
            )
        return GuardDecision.allow()

    # ── Usage limit checks ──────────────────────────────────────────────

    def check_usage_limits(self, usage_snapshot: dict) -> GuardDecision:
        """Check session / user / account token limits.

        Returns denial for the *most actionable* exceeded limit.
        Precedence: session → user → account.
        """
        checks = [
            (
                self.policy.session_token_limit,
                usage_snapshot.get("session_total_tokens", 0),
                DenialReason.SESSION_TOKEN_LIMIT,
                "Session token limit reached.",
            ),
            (
                self.policy.user_token_limit,
                usage_snapshot.get("user_total_tokens", 0),
                DenialReason.USER_TOKEN_LIMIT,
                "Your usage limit has been reached.",
            ),
            (
                self.policy.account_token_limit,
                usage_snapshot.get("account_total_tokens", 0),
                DenialReason.ACCOUNT_TOKEN_LIMIT,
                "Account usage limit has been reached.",
            ),
        ]
        for limit, used, reason, message in checks:
            if limit is not None and used >= limit:
                return GuardDecision.deny(reason, message)
        return GuardDecision.allow()

    # ── Internals ───────────────────────────────────────────────────────

    def _deny_for_current_state(self) -> GuardDecision:
        """Build a denial based on the current guard_state."""
        state = self.presence.guard_state
        reason_map = {
            GuardState.PAUSED_INACTIVITY: (
                DenialReason.SESSION_PAUSED,
                "Session is paused due to inactivity.",
            ),
            GuardState.PAUSED_RUNTIME_CAP: (
                DenialReason.RUNTIME_CAP_REACHED,
                "Session runtime cap reached — engine progression stopped.",
            ),
            GuardState.LOCKED_USAGE: (
                DenialReason.CHAT_SEND_LOCKED,
                "Session locked due to usage limits.",
            ),
            GuardState.ENDED: (
                DenialReason.RUNTIME_CAP_REACHED,
                "Session has ended.",
            ),
        }
        reason, message = reason_map.get(
            state, (DenialReason.SESSION_PAUSED, "Session is not runnable.")
        )
        return GuardDecision.deny(reason, message)

    def _remaining_budget(self, usage_snapshot: dict) -> int | None:
        """Return the smallest remaining budget across all applicable limits.

        Returns ``None`` if no limits are configured.
        """
        remainders: list[int] = []
        if self.policy.session_token_limit is not None:
            remainders.append(
                self.policy.session_token_limit - usage_snapshot.get("session_total_tokens", 0)
            )
        if self.policy.user_token_limit is not None:
            remainders.append(
                self.policy.user_token_limit - usage_snapshot.get("user_total_tokens", 0)
            )
        if self.policy.account_token_limit is not None:
            remainders.append(
                self.policy.account_token_limit - usage_snapshot.get("account_total_tokens", 0)
            )
        if not remainders:
            return None
        return min(remainders)
