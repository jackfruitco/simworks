"""API schemas for the guard framework."""

from __future__ import annotations

from ninja import Field, Schema


class HeartbeatIn(Schema):
    """Client heartbeat payload."""

    client_visibility: str = "unknown"


class GuardStateOut(Schema):
    """Current guard state for a session."""

    guard_state: str
    pause_reason: str
    engine_runnable: bool
    active_elapsed_seconds: int = 0
    runtime_cap_seconds: int | None = None
    wall_clock_expires_at: str | None = None
    warnings: list[str] = Field(default_factory=list)
    denial_reason: str | None = None
    denial_message: str | None = None
