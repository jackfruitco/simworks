"""TrainerLab API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from apps.trainerlab.models import TrainerSession


class LabAccessOut(BaseModel):
    lab_slug: str
    access_level: Literal["viewer", "instructor", "admin"]


class TrainerSessionCreateIn(BaseModel):
    scenario_spec: dict[str, Any] = Field(default_factory=dict)
    directives: str | None = None
    modifiers: list[str] = Field(default_factory=list)


class TrainerSessionOut(BaseModel):
    id: int
    simulation_id: int
    status: str
    scenario_spec: dict[str, Any]
    runtime_state: dict[str, Any]
    initial_directives: str | None
    tick_interval_seconds: int
    run_started_at: datetime | None
    run_paused_at: datetime | None
    run_completed_at: datetime | None
    last_ai_tick_at: datetime | None
    created_at: datetime
    modified_at: datetime


class TrainerCommandAck(BaseModel):
    command_id: str
    status: str = "accepted"


class SteerPromptIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


class InjuryCreateIn(BaseModel):
    injury_category: str
    injury_location: str
    injury_kind: str
    injury_description: str
    parent_injury_id: int | None = None
    supersedes_event_id: int | None = None


class IllnessCreateIn(BaseModel):
    name: str
    description: str = ""
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    is_resolved: bool = False
    supersedes_event_id: int | None = None


class InterventionCreateIn(BaseModel):
    code: str = ""
    description: str = ""
    target: str = ""
    supersedes_event_id: int | None = None


class VitalCreateIn(BaseModel):
    vital_type: Literal["heart_rate", "spo2", "etco2", "blood_glucose", "blood_pressure"]
    min_value: int
    max_value: int
    lock_value: bool = False
    min_value_diastolic: int | None = None
    max_value_diastolic: int | None = None
    supersedes_event_id: int | None = None


class RuntimeEventOut(BaseModel):
    event_id: str
    event_type: str
    created_at: datetime
    correlation_id: str | None = None
    payload: dict[str, Any]


class RunSummaryOut(BaseModel):
    session_id: int
    simulation_id: int
    status: str
    run_started_at: str | None
    run_completed_at: str | None
    final_state: dict[str, Any]
    event_type_counts: dict[str, int]
    timeline_highlights: list[dict[str, Any]]
    command_log: list[dict[str, Any]]
    ai_rationale_notes: list[Any]


class SSEEnvelope(BaseModel):
    event_id: str
    event_type: str
    created_at: datetime
    correlation_id: str | None = None
    payload: dict[str, Any]


def trainer_session_to_out(session: TrainerSession) -> TrainerSessionOut:
    return TrainerSessionOut(
        id=session.id,
        simulation_id=session.simulation_id,
        status=session.status,
        scenario_spec=session.scenario_spec_json or {},
        runtime_state=session.runtime_state_json or {},
        initial_directives=session.initial_directives or None,
        tick_interval_seconds=session.tick_interval_seconds,
        run_started_at=session.run_started_at,
        run_paused_at=session.run_paused_at,
        run_completed_at=session.run_completed_at,
        last_ai_tick_at=session.last_ai_tick_at,
        created_at=session.created_at,
        modified_at=session.modified_at,
    )
