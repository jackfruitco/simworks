"""Simulation schemas for API v1."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.common.retries import (
    has_user_retries_remaining,
    is_simulation_initial_generation_retryable,
)


class SimulationOut(BaseModel):
    """Output schema for a simulation.

    This is the primary bootstrap response for ChatLab clients.  After loading
    this snapshot, the client should open the ChatLab WebSocket and send
    ``session.hello`` with ``latest_event_id`` as the optional replay anchor.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Simulation ID")
    user_id: int = Field(..., description="Owner user ID")
    start_timestamp: datetime = Field(..., description="When the simulation started")
    end_timestamp: datetime | None = Field(
        default=None,
        description="When the simulation ended (null if in progress)",
    )
    time_limit_seconds: int | None = Field(
        default=None,
        description="Time limit in seconds (null if no limit)",
    )
    diagnosis: str | None = Field(default=None, description="Diagnosis for this simulation")
    chief_complaint: str | None = Field(
        default=None,
        description="Chief complaint for this simulation",
    )
    patient_display_name: str = Field(
        ...,
        description="Display name for the simulated patient",
    )
    patient_initials: str = Field(
        ...,
        description="Initials for the simulated patient",
    )
    status: Literal["in_progress", "completed", "timed_out", "failed", "canceled"] = Field(
        ...,
        description="Current status of the simulation",
    )
    terminal_reason_code: str = Field(
        default="",
        description="Machine-readable terminal reason code",
    )
    terminal_reason_text: str = Field(
        default="",
        description="User-safe terminal reason text",
    )
    terminal_at: datetime | None = Field(
        default=None,
        description="Timestamp when simulation entered terminal state",
    )
    retryable: bool | None = Field(
        default=None,
        description="Whether the failed simulation can be retried by the user",
    )
    latest_event_id: str | None = Field(
        default=None,
        description=(
            "Event ID (UUID) of the most recent durable outbox event for this simulation. "
            "Pass this value as ``last_event_id`` in the ChatLab ``session.hello`` or "
            "``session.resume`` payload so the server can replay durable events strictly "
            "after this point. ``null`` when no durable events exist yet."
        ),
    )


class SimulationCreate(BaseModel):
    """Input schema for creating a simulation."""

    diagnosis: str | None = Field(
        default=None,
        description="Diagnosis for the simulation",
        max_length=255,
    )
    chief_complaint: str | None = Field(
        default=None,
        description="Chief complaint for the simulation",
        max_length=255,
    )
    patient_full_name: str = Field(
        ...,
        description="Full name for the simulated patient",
        max_length=100,
        min_length=1,
    )
    time_limit_seconds: int | None = Field(
        default=None,
        description="Time limit in seconds (null for no limit)",
        ge=60,  # Minimum 1 minute
        le=86400,  # Maximum 24 hours
    )


class SimulationQuickCreate(BaseModel):
    """Input schema for one-tap ChatLab simulation creation."""

    modifiers: list[str] = Field(
        default_factory=list,
        description="Optional simulation modifier keys to apply.",
    )


class SimulationEndResponse(BaseModel):
    """Response for ending a simulation."""

    id: int = Field(..., description="Simulation ID")
    end_timestamp: datetime = Field(..., description="When the simulation was ended")
    status: Literal["completed"] = Field(
        default="completed",
        description="Final status",
    )


def simulation_to_out(sim) -> SimulationOut:
    """Convert a Simulation model instance to SimulationOut schema."""
    from apps.common.outbox.outbox import get_latest_event_id_sync

    raw_status = getattr(sim, "status", None)
    if raw_status in {"completed", "timed_out", "failed", "canceled"}:
        status = raw_status
    elif raw_status == "in_progress":
        if sim.is_timed_out:
            status = "timed_out"
        elif sim.end_timestamp:
            status = "completed"
        else:
            status = "in_progress"
    elif sim.is_timed_out:
        status = "timed_out"
    elif sim.is_complete:
        status = "completed"
    else:
        status = "in_progress"

    terminal_reason_code = getattr(sim, "terminal_reason_code", "") or ""
    retryable: bool | None = None
    if status == "failed":
        retryable = is_simulation_initial_generation_retryable(sim) and (
            has_user_retries_remaining(getattr(sim, "initial_retry_count", 0))
        )

    return SimulationOut(
        id=sim.pk,
        user_id=sim.user_id,
        start_timestamp=sim.start_timestamp,
        end_timestamp=sim.end_timestamp,
        time_limit_seconds=int(sim.time_limit.total_seconds()) if sim.time_limit else None,
        diagnosis=sim.diagnosis,
        chief_complaint=sim.chief_complaint,
        patient_display_name=sim.sim_patient_display_name,
        patient_initials=sim.sim_patient_initials,
        status=status,
        terminal_reason_code=terminal_reason_code,
        terminal_reason_text=getattr(sim, "terminal_reason_text", "") or "",
        terminal_at=getattr(sim, "terminal_at", None),
        retryable=retryable,
        latest_event_id=get_latest_event_id_sync(sim.pk),
    )
