"""TrainerLab API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from apps.trainerlab.models import (
    ScenarioInstruction,
    ScenarioInstructionPermission,
    TrainerSession,
)


class LabAccessOut(BaseModel):
    lab_slug: str
    access_level: Literal["viewer", "instructor", "admin"]


class TrainerSessionCreateIn(BaseModel):
    scenario_spec: dict[str, Any] = Field(default_factory=dict)
    directives: str | None = None
    modifiers: list[str] = Field(default_factory=list)


class TrainerRunOut(BaseModel):
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


class SimulationAdjustIn(BaseModel):
    target: Literal["trend", "injury", "avpu", "intervention", "note"]
    direction: Literal["up", "down", "same", "worsen", "improve", "set", "add"] | None = None
    magnitude: int | None = Field(default=None, ge=1, le=10)
    injury_event_id: int | None = None
    injury_region: str | None = None
    avpu_state: Literal["alert", "verbal", "pain", "unalert"] | None = None
    intervention_code: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationAdjustAck(BaseModel):
    command_id: str
    status: str = "accepted"
    simulation_id: int


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


class ScenarioInstructionCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str = ""
    instruction_text: str = ""
    injuries: list[str] = Field(default_factory=list)
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioInstructionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    instruction_text: str | None = None
    injuries: list[str] | None = None
    severity: Literal["low", "moderate", "high", "critical"] | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


class ScenarioInstructionPermissionIn(BaseModel):
    user_id: int
    can_read: bool = True
    can_edit: bool = False
    can_delete: bool = False
    can_share: bool = False
    can_duplicate: bool = True


class ScenarioInstructionUnshareIn(BaseModel):
    user_id: int


class ScenarioInstructionApplyIn(BaseModel):
    simulation_id: int


class ScenarioInstructionPermissionOut(BaseModel):
    user_id: int
    can_read: bool
    can_edit: bool
    can_delete: bool
    can_share: bool
    can_duplicate: bool


class ScenarioInstructionOut(BaseModel):
    id: int
    owner_id: int
    title: str
    description: str
    instruction_text: str
    injuries: list[str]
    severity: str
    metadata: dict[str, Any]
    is_active: bool
    permissions: list[ScenarioInstructionPermissionOut]
    created_at: datetime
    modified_at: datetime


class DictionaryItemOut(BaseModel):
    code: str
    label: str


class InterventionGroupOut(BaseModel):
    group: str
    items: list[DictionaryItemOut]


def trainer_run_to_out(session: TrainerSession) -> TrainerRunOut:
    return TrainerRunOut(
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


def scenario_permission_to_out(
    permission: ScenarioInstructionPermission,
) -> ScenarioInstructionPermissionOut:
    return ScenarioInstructionPermissionOut(
        user_id=permission.user_id,
        can_read=permission.can_read,
        can_edit=permission.can_edit,
        can_delete=permission.can_delete,
        can_share=permission.can_share,
        can_duplicate=permission.can_duplicate,
    )


def scenario_instruction_to_out(
    instruction: ScenarioInstruction,
) -> ScenarioInstructionOut:
    permissions = list(instruction.permissions.all())
    return ScenarioInstructionOut(
        id=instruction.id,
        owner_id=instruction.owner_id,
        title=instruction.title,
        description=instruction.description,
        instruction_text=instruction.instruction_text,
        injuries=list(instruction.injuries_json or []),
        severity=instruction.severity,
        metadata=dict(instruction.metadata_json or {}),
        is_active=instruction.is_active,
        permissions=[scenario_permission_to_out(item) for item in permissions],
        created_at=instruction.created_at,
        modified_at=instruction.modified_at,
    )
