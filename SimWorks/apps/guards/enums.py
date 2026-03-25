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
    PAUSED_RUNTIME_CAP = "paused_runtime_cap", "Paused (Runtime Cap)"
    LOCKED_USAGE = "locked_usage", "Locked (Usage)"
    ENDED = "ended", "Ended"


# States where the simulation engine may NOT progress.
NON_RUNNABLE_STATES = frozenset(
    {
        GuardState.PAUSED_INACTIVITY,
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
        GuardState.LOCKED_USAGE,
    }
)


class PauseReason(models.TextChoices):
    """Why a session was paused."""

    NONE = "none", "None"
    INACTIVITY = "inactivity", "Inactivity"
    RUNTIME_CAP = "runtime_cap", "Runtime Cap"
    USAGE_LIMIT = "usage_limit", "Usage Limit"
    WALL_CLOCK_EXPIRY = "wall_clock_expiry", "Wall-Clock Expiry"
    MANUAL = "manual", "Manual"


class DenialReason(models.TextChoices):
    """Structured reason codes returned when a guard check denies a request."""

    SESSION_PAUSED = "session_paused", "Session is paused"
    RUNTIME_CAP_REACHED = "runtime_cap_reached", "Runtime cap reached"
    SESSION_TOKEN_LIMIT = "session_token_limit", "Session token limit reached"
    USER_TOKEN_LIMIT = "user_token_limit", "Your usage limit reached"
    ACCOUNT_TOKEN_LIMIT = "account_token_limit", "Account usage limit reached"
    INSUFFICIENT_TOKEN_BUDGET = "insufficient_token_budget", "Insufficient token budget"
    WALL_CLOCK_EXPIRED = "wall_clock_expired", "Session wall-clock expired"
    CHAT_SEND_LOCKED = "chat_send_locked", "Sending locked due to usage"


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
