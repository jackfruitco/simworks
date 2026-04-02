"""API schemas for the guard framework."""

from __future__ import annotations

from typing import Any

from ninja import Field, Schema


class HeartbeatIn(Schema):
    """Client heartbeat payload."""

    client_visibility: str = "unknown"


class GuardSignalOut(Schema):
    """Structured guard signal — warning or denial.

    Clients should branch on ``code`` for logic, render ``message`` for
    display, and use ``resumable`` / ``terminal`` to decide UI affordances.
    """

    code: str
    severity: str  # "warning" or "error"
    title: str | None = None
    message: str
    resumable: bool | None = None
    terminal: bool | None = None
    expires_in_seconds: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuardStateOut(Schema):
    """Current guard state for a session."""

    guard_state: str
    guard_reason: str
    engine_runnable: bool
    active_elapsed_seconds: int = 0
    runtime_cap_seconds: int | None = None
    wall_clock_expires_at: str | None = None
    warnings: list[GuardSignalOut] = Field(default_factory=list)
    denial: GuardSignalOut | None = None
