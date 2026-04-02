"""Canonical enums for the guard framework.

These enums are shared across TrainerLab, ChatLab, and any future labs.
Prefer these over magic strings in all guard-related code.
"""

from __future__ import annotations

from django.db import models


class GuardState(models.TextChoices):
    """Persisted guard state for a session."""

    ACTIVE = "active", "Active"
    IDLE = "idle", "Idle"
    WARNING = "warning", "Warning"
    PAUSED_INACTIVITY = "paused_inactivity", "Paused (Inactivity)"
    PAUSED_MANUAL = "paused_manual", "Paused (Manual)"
    PAUSED_RUNTIME_CAP = "paused_runtime_cap", "Paused (Runtime Cap)"
    LOCKED_USAGE = "locked_usage", "Locked (Usage)"
    ENDED = "ended", "Ended"


# States where the simulation engine may NOT progress.
NON_RUNNABLE_STATES = frozenset(
    {
        GuardState.PAUSED_INACTIVITY,
        GuardState.PAUSED_MANUAL,
        GuardState.PAUSED_RUNTIME_CAP,
        GuardState.LOCKED_USAGE,
        GuardState.ENDED,
    }
)

# States considered terminal — no further transitions except cleanup.
TERMINAL_GUARD_STATES = frozenset(
    {
        GuardState.PAUSED_RUNTIME_CAP,
        GuardState.ENDED,
    }
)

RESUMABLE_GUARD_STATES = frozenset(
    {
        GuardState.PAUSED_INACTIVITY,
        GuardState.PAUSED_MANUAL,
        GuardState.LOCKED_USAGE,
    }
)


class PauseReason(models.TextChoices):
    """Why a session entered its current state.

    Exposed publicly as ``guard_reason`` in the API contract.
    The internal model field remains ``pause_reason`` to avoid migration churn.
    """

    NONE = "none", "None"
    INACTIVITY = "inactivity", "Inactivity"
    RUNTIME_CAP = "runtime_cap", "Runtime Cap"
    USAGE_LIMIT = "usage_limit", "Usage Limit"
    WALL_CLOCK_EXPIRY = "wall_clock_expiry", "Wall-Clock Expiry"
    MANUAL = "manual", "Manual"
    USER_ENDED = "user_ended", "User Ended"
    ADMIN_ENDED = "admin_ended", "Admin Ended"
    SESSION_EXPIRY = "session_expiry", "Session Expiry"


class DenialReason(models.TextChoices):
    """Canonical public denial codes for the guard API contract.

    These values are the **single source of truth** for external-facing
    denial codes.  ``presentation.py`` maps guard states to these codes;
    ``decisions.py`` uses them internally.  Clients branch on these codes.
    """

    SESSION_PAUSED = "session_paused", "Session is paused"
    RUNTIME_CAP_REACHED = "runtime_cap_reached", "Runtime cap reached"
    SESSION_ENDED = "session_ended", "Session has ended"
    USAGE_LIMIT_REACHED = "usage_limit_reached", "Usage limit reached"
    SESSION_TOKEN_LIMIT = "session_token_limit", "Session token limit reached"
    USER_TOKEN_LIMIT = "user_token_limit", "Your usage limit reached"
    ACCOUNT_TOKEN_LIMIT = "account_token_limit", "Account usage limit reached"
    INSUFFICIENT_TOKEN_BUDGET = "insufficient_token_budget", "Insufficient token budget"


class ClientVisibility(models.TextChoices):
    """Client-reported visibility / foreground state."""

    FOREGROUND = "foreground", "Foreground"
    BACKGROUND = "background", "Background"
    UNKNOWN = "unknown", "Unknown"


class LabType(models.TextChoices):
    """Lab / product surface type."""

    TRAINERLAB = "trainerlab", "TrainerLab"
    CHATLAB = "chatlab", "ChatLab"


class UsageScopeType(models.TextChoices):
    """Scope level for usage aggregation."""

    SESSION = "session", "Session"
    USER = "user", "User"
    ACCOUNT = "account", "Account"
