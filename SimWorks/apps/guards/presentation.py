"""Guard signal presentation layer.

Translates internal guard state and decisions into API-ready structured
objects.  This is the single canonical place that defines user-facing
guard semantics (codes, titles, messages, resumability, terminality).

All API endpoints should use these builders rather than constructing
warning or denial payloads inline.
"""

from __future__ import annotations

from typing import Any

from .enums import GuardState, PauseReason

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
# ───────────────────────────────────────────────────────────────────────

_DENIAL_MAP: dict[str, dict[str, Any]] = {
    GuardState.PAUSED_INACTIVITY: {
        "code": "session_paused",
        "title": "Session paused",
        "message": "Session is paused due to inactivity.",
        "resumable": True,
        "terminal": False,
    },
    GuardState.PAUSED_MANUAL: {
        "code": "session_paused",
        "title": "Session paused",
        "message": "Session is manually paused.",
        "resumable": True,
        "terminal": False,
    },
    GuardState.PAUSED_RUNTIME_CAP: {
        "code": "runtime_cap_reached",
        "title": "Runtime limit reached",
        "message": "Engine progression is no longer available for this session.",
        "resumable": False,
        "terminal": True,
    },
    GuardState.LOCKED_USAGE: {
        "code": "usage_limit_reached",
        "title": "Usage limit reached",
        "message": "Session locked due to usage limits.",
        "resumable": True,
        "terminal": False,
    },
    GuardState.ENDED: {
        "code": "session_ended",
        "title": "Session ended",
        "message": "Session has ended.",
        "resumable": False,
        "terminal": True,
    },
}

_DENIAL_FALLBACK = {
    "code": "session_paused",
    "title": "Session unavailable",
    "message": "Session is not runnable.",
    "resumable": False,
    "terminal": False,
}


def denial_for_state(
    guard_state: str,
    pause_reason: str = PauseReason.NONE,
) -> dict[str, Any] | None:
    """Return the canonical denial signal for a non-runnable guard state.

    Returns ``None`` if the state is runnable (no denial applies).
    """
    entry = _DENIAL_MAP.get(guard_state)
    if entry is None:
        # If the state isn't in the map, it's either runnable or unknown.
        from .enums import NON_RUNNABLE_STATES

        if guard_state not in NON_RUNNABLE_STATES:
            return None
        entry = _DENIAL_FALLBACK

    return build_denial_signal(
        code=entry["code"],
        message=entry["message"],
        title=entry["title"],
        resumable=entry["resumable"],
        terminal=entry["terminal"],
        metadata={
            "guard_state": guard_state,
            "pause_reason": pause_reason,
        },
    )


def denial_from_decision(
    denial_reason: str,
    denial_message: str,
    guard_state: str = "",
    pause_reason: str = PauseReason.NONE,
) -> dict[str, Any]:
    """Build a denial signal from a ``GuardDecision``'s denial fields.

    Used when a ``GuardDecision`` is denied but we're not in a state
    that maps cleanly to ``denial_for_state`` (e.g. chat send-lock
    from budget exhaustion).
    """
    # Try the state-based map first for canonical semantics.
    if guard_state:
        state_denial = denial_for_state(guard_state, pause_reason)
        if state_denial is not None:
            return state_denial

    # Fall back to a signal built from the decision's raw fields.
    return build_denial_signal(
        code=denial_reason or "guard_denied",
        message=denial_message or "Action denied by guard.",
        title="Action denied",
        resumable=None,
        terminal=None,
        metadata={
            "guard_state": guard_state,
            "pause_reason": pause_reason,
        },
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


def warning_approaching_usage_limit(
    estimated_turns: int,
    remaining_tokens: int,
) -> dict[str, Any]:
    """Structured warning for sessions nearing a token usage limit."""
    return build_warning_signal(
        code="approaching_usage_limit",
        title="Usage limit approaching",
        message=f"Approximately {estimated_turns} message(s) remaining.",
        metadata={
            "estimated_turns": estimated_turns,
            "remaining_tokens": remaining_tokens,
        },
    )
