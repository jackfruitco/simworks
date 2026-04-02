"""Guard signal presentation layer.

Translates internal guard state and decisions into API-ready structured
objects.  This is the single canonical place that defines user-facing
guard semantics (codes, titles, messages, resumability, terminality).

All API endpoints should use these builders rather than constructing
warning or denial payloads inline.

The public denial codes are defined in ``enums.DenialReason`` — this
module maps guard states to those codes.  No other module should invent
external-facing codes.
"""

from __future__ import annotations

from typing import Any

from .enums import (
    RESUMABLE_GUARD_STATES,
    TERMINAL_GUARD_STATES,
    DenialReason,
    GuardState,
    PauseReason,
)

# ───────────────────────────────────────────────────────────────────────
# Generic builders
# ───────────────────────────────────────────────────────────────────────


def build_warning_signal(
    *,
    code: str,
    message: str,
    title: str | None = None,
    expires_in_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured warning signal dict matching ``GuardSignalOut``."""
    return {
        "code": code,
        "severity": "warning",
        "title": title,
        "message": message,
        "resumable": None,
        "terminal": None,
        "expires_in_seconds": expires_in_seconds,
        "metadata": metadata or {},
    }


def build_denial_signal(
    *,
    code: str,
    message: str,
    title: str | None = None,
    resumable: bool | None = None,
    terminal: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured denial signal dict matching ``GuardSignalOut``."""
    return {
        "code": code,
        "severity": "error",
        "title": title,
        "message": message,
        "resumable": resumable,
        "terminal": terminal,
        "expires_in_seconds": None,
        "metadata": metadata or {},
    }


# ───────────────────────────────────────────────────────────────────────
# Canonical denial map — guard state → structured signal
#
# Uses DenialReason enum values as the single public code vocabulary.
# This must stay in sync with RuntimeGuard._deny_for_current_state()
# in decisions.py (same codes, but this layer adds presentation
# semantics like resumable/terminal/title).
# ───────────────────────────────────────────────────────────────────────

_DENIAL_MAP: dict[str, dict[str, Any]] = {
    GuardState.PAUSED_INACTIVITY: {
        "code": DenialReason.SESSION_PAUSED,
        "title": "Session paused",
        "message": "Session is paused due to inactivity.",
    },
    GuardState.PAUSED_MANUAL: {
        "code": DenialReason.SESSION_PAUSED,
        "title": "Session paused",
        "message": "Session is manually paused.",
    },
    GuardState.PAUSED_RUNTIME_CAP: {
        "code": DenialReason.RUNTIME_CAP_REACHED,
        "title": "Runtime limit reached",
        "message": "Engine progression is no longer available for this session.",
    },
    GuardState.LOCKED_USAGE: {
        "code": DenialReason.USAGE_LIMIT_REACHED,
        "title": "Usage limit reached",
        "message": "Session locked due to usage limits.",
    },
    GuardState.ENDED: {
        "code": DenialReason.SESSION_ENDED,
        "title": "Session ended",
        "message": "Session has ended.",
    },
}

_DENIAL_FALLBACK = {
    "code": DenialReason.SESSION_PAUSED,
    "title": "Session unavailable",
    "message": "Session is not runnable.",
}


def denial_for_state(
    guard_state: str,
    pause_reason: str = PauseReason.NONE,
) -> dict[str, Any] | None:
    """Return the canonical denial signal for a non-runnable guard state.

    Returns ``None`` if the state is runnable (no denial applies).
    """
    from .enums import NON_RUNNABLE_STATES

    entry = _DENIAL_MAP.get(guard_state)
    if entry is None:
        if guard_state not in NON_RUNNABLE_STATES:
            return None
        entry = _DENIAL_FALLBACK

    return build_denial_signal(
        code=entry["code"],
        message=entry["message"],
        title=entry["title"],
        resumable=guard_state in RESUMABLE_GUARD_STATES,
        terminal=guard_state in TERMINAL_GUARD_STATES,
        metadata={
            "guard_state": guard_state,
            "pause_reason": pause_reason,
        },
    )


# ───────────────────────────────────────────────────────────────────────
# Non-state (reason-based) denial mapper
#
# For denials that happen before a guard-state transition (e.g. send-lock
# from budget exhaustion, pre-session budget check), this mapper turns
# the DenialReason code into a fully-specified signal with title,
# resumable/terminal, and sensible defaults.
# ───────────────────────────────────────────────────────────────────────

_REASON_SIGNAL_MAP: dict[str, dict[str, Any]] = {
    DenialReason.USAGE_LIMIT_REACHED: {
        "title": "Usage limit reached",
        "resumable": True,
        "terminal": False,
    },
    DenialReason.INSUFFICIENT_TOKEN_BUDGET: {
        "title": "Insufficient token budget",
        "resumable": False,
        "terminal": False,
    },
    DenialReason.SESSION_TOKEN_LIMIT: {
        "title": "Session token limit reached",
        "resumable": False,
        "terminal": False,
    },
    DenialReason.USER_TOKEN_LIMIT: {
        "title": "Usage limit reached",
        "resumable": False,
        "terminal": False,
    },
    DenialReason.ACCOUNT_TOKEN_LIMIT: {
        "title": "Account usage limit reached",
        "resumable": False,
        "terminal": False,
    },
    DenialReason.RUNTIME_CAP_REACHED: {
        "title": "Runtime limit reached",
        "resumable": False,
        "terminal": True,
    },
    DenialReason.SESSION_PAUSED: {
        "title": "Session paused",
        "resumable": True,
        "terminal": False,
    },
    DenialReason.SESSION_ENDED: {
        "title": "Session ended",
        "resumable": False,
        "terminal": True,
    },
    DenialReason.WALL_CLOCK_EXPIRED: {
        "title": "Session expired",
        "resumable": False,
        "terminal": True,
    },
}


def denial_from_reason(
    denial_reason: str,
    denial_message: str = "",
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical denial signal from a ``DenialReason`` code.

    Used when a ``GuardDecision`` is denied but no guard-state transition
    has occurred yet (e.g. send-lock from budget exhaustion before the
    session enters ``locked_usage``).

    Unlike the generic ``build_denial_signal()`` fallback, this always
    produces a fully-specified signal with canonical title, resumable,
    and terminal values for known denial reasons.
    """
    spec = _REASON_SIGNAL_MAP.get(denial_reason, {})
    return build_denial_signal(
        code=denial_reason,
        message=denial_message or "Action denied by guard.",
        title=spec.get("title", "Action denied"),
        resumable=spec.get("resumable"),
        terminal=spec.get("terminal"),
        metadata=metadata or {},
    )


# ───────────────────────────────────────────────────────────────────────
# Warning builders
# ───────────────────────────────────────────────────────────────────────


def warning_approaching_runtime_cap(
    remaining_seconds: int,
    cap_seconds: int | None = None,
) -> dict[str, Any]:
    """Structured warning for sessions nearing the active runtime cap."""
    meta: dict[str, Any] = {"remaining_seconds": remaining_seconds}
    if cap_seconds is not None:
        meta["cap_seconds"] = cap_seconds
    return build_warning_signal(
        code="approaching_runtime_cap",
        title="Runtime limit approaching",
        message=f"{remaining_seconds} seconds of active runtime remaining.",
        expires_in_seconds=remaining_seconds,
        metadata=meta,
    )


def warning_inactivity(seconds_until_pause: int) -> dict[str, Any]:
    """Structured warning for sessions about to be paused for inactivity."""
    return build_warning_signal(
        code="inactivity_warning",
        title="Inactivity detected",
        message=f"Session will pause in {seconds_until_pause} seconds due to inactivity.",
        expires_in_seconds=seconds_until_pause,
        metadata={"seconds_until_pause": seconds_until_pause},
    )
