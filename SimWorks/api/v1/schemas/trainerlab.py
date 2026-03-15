"""TrainerLab API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.trainerlab.injury_dictionary import (
    normalize_injury_category,
    normalize_injury_kind,
    normalize_injury_location,
)
from apps.trainerlab.intervention_dictionary import (
    normalize_intervention_site,
    normalize_intervention_type,
    normalize_site_code,
    validate_intervention_details,
)
from apps.trainerlab.models import (
    ScenarioInstruction,
    ScenarioInstructionPermission,
    TrainerSession,
)
from apps.trainerlab.schemas import RuntimeInstructorIntent, RuntimePatientStatus


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
    injury_category: str = Field(
        ...,
        description="Injury category code or friendly label (normalized to canonical code)",
    )
    injury_location: str = Field(
        ...,
        description="Injury location code or friendly label (normalized to canonical code)",
    )
    injury_kind: str = Field(
        ...,
        description="Injury kind code or friendly label (normalized to canonical code)",
    )
    injury_description: str
    parent_injury_id: int | None = None
    supersedes_event_id: int | None = None

    @field_validator("injury_category")
    @classmethod
    def _normalize_injury_category(cls, value: str) -> str:
        return normalize_injury_category(value)

    @field_validator("injury_location")
    @classmethod
    def _normalize_injury_location(cls, value: str) -> str:
        return normalize_injury_location(value)

    @field_validator("injury_kind")
    @classmethod
    def _normalize_injury_kind(cls, value: str) -> str:
        return normalize_injury_kind(value)


class IllnessCreateIn(BaseModel):
    name: str
    description: str = ""
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    is_resolved: bool = False
    supersedes_event_id: int | None = None


class InterventionDetailsIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    version: int = 1


class InterventionCreateIn(BaseModel):
    intervention_type: str = Field(
        ...,
        description="Intervention type code or friendly label",
    )
    site_code: str = Field(
        ...,
        description="Intervention site code or friendly label, normalized per intervention type",
    )
    target_injury_id: int | None = None
    status: Literal["applied", "adjusted", "reassessed", "removed"] = "applied"
    effectiveness: Literal[
        "unknown",
        "effective",
        "partially_effective",
        "ineffective",
    ] = "unknown"
    notes: str = ""
    details: InterventionDetailsIn = Field(
        ...,
        description=(
            "Typed intervention-specific details. `details.kind` must match `intervention_type`."
        ),
    )
    performed_by_role: Literal["trainee", "instructor", "ai"] = "trainee"
    supersedes_event_id: int | None = None

    @field_validator("intervention_type")
    @classmethod
    def _normalize_intervention_type(cls, value: str) -> str:
        return normalize_intervention_type(value)

    @field_validator("site_code", mode="before")
    @classmethod
    def _normalize_site_code(cls, v: str) -> str:
        return normalize_site_code(v)

    @model_validator(mode="after")
    def _normalize_site_and_validate_detail_shape(self) -> "InterventionCreateIn":
        self.site_code = normalize_site_code(
            normalize_intervention_site(self.intervention_type, self.site_code)
        )
        validated = validate_intervention_details(
            self.intervention_type,
            self.details.model_dump(exclude_none=True),
        )
        self.details = InterventionDetailsIn.model_validate(validated)
        return self


class SimulationNoteCreateIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    send_to_ai: bool = False
    performed_by_role: Literal["trainee", "instructor", "ai"] = "instructor"

    @field_validator("content")
    @classmethod
    def _normalize_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class VitalCreateIn(BaseModel):
    vital_type: Literal[
        "heart_rate",
        "respiratory_rate",
        "spo2",
        "etco2",
        "blood_glucose",
        "blood_pressure",
    ]
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
    notes: list[dict[str, Any]] = Field(default_factory=list)
    command_log: list[dict[str, Any]]
    ai_rationale_notes: list[Any]
    ai_debrief: dict[str, Any] | None = None


class RuntimeConditionStateOut(BaseModel):
    domain_event_id: int | None = None
    kind: Literal["injury", "illness"]
    label: str
    status: str
    source: str | None = None
    timestamp: str | None = None
    injury_category: str | None = None
    injury_location: str | None = None
    injury_kind: str | None = None
    description: str | None = None
    severity: str | None = None


class RuntimeInterventionStateOut(BaseModel):
    domain_event_id: int | None = None
    intervention_type: str | None = None
    site_code: str | None = None
    effectiveness: str = "unknown"
    notes: str = ""
    code: str = ""
    description: str = ""
    target: str = ""
    anatomic_location: str = ""
    performed_by_role: str = "trainee"
    status: str = "active"
    clinical_effect: str = ""
    source: str | None = None
    timestamp: str | None = None


class RuntimeVitalStateOut(BaseModel):
    domain_event_id: int | None = None
    vital_type: Literal[
        "heart_rate",
        "respiratory_rate",
        "spo2",
        "etco2",
        "blood_glucose",
        "blood_pressure",
    ]
    min_value: int
    max_value: int
    lock_value: bool = False
    min_value_diastolic: int | None = None
    max_value_diastolic: int | None = None
    trend: str = "stable"
    source: str | None = None
    timestamp: str | None = None


class TrainerRuntimeSnapshotOut(BaseModel):
    conditions: list[RuntimeConditionStateOut] = Field(default_factory=list)
    interventions: list[RuntimeInterventionStateOut] = Field(default_factory=list)
    vitals: list[RuntimeVitalStateOut] = Field(default_factory=list)
    patient_status: RuntimePatientStatus = Field(default_factory=RuntimePatientStatus)


class ScenarioBriefOut(BaseModel):
    read_aloud_brief: str = ""
    environment: str = ""
    location_overview: str = ""
    threat_context: str = ""
    evacuation_options: str = ""
    evacuation_time: str = ""
    special_considerations: str = ""


class TrainerRuntimeStateOut(BaseModel):
    simulation_id: int
    session_id: int
    status: str
    state_revision: int
    active_elapsed_seconds: int
    scenario_brief: ScenarioBriefOut | None = None
    current_snapshot: TrainerRuntimeSnapshotOut
    ai_plan: RuntimeInstructorIntent
    ai_rationale_notes: list[str] = Field(default_factory=list)
    pending_runtime_reasons: list[dict[str, Any]] = Field(default_factory=list)
    currently_processing_reasons: list[dict[str, Any]] = Field(default_factory=list)
    last_runtime_error: str = ""
    last_ai_tick_at: datetime | None = None


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


class InterventionUIFieldOut(BaseModel):
    name: str
    label: str
    input_type: str
    required: bool = True
    help_text: str = ""
    options: list[DictionaryItemOut] = Field(default_factory=list)


class InterventionDetailsSchemaOut(BaseModel):
    kind: str
    version: int
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    allows_extra: bool = False


class InterventionDefinitionOut(BaseModel):
    code: str
    label: str
    sites: list[DictionaryItemOut]
    details_schema: InterventionDetailsSchemaOut
    ui_fields: list[InterventionUIFieldOut] = Field(default_factory=list)


class InterventionDictionaryOut(BaseModel):
    interventions: list[InterventionDefinitionOut]


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


def _join_if_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value or "")


def trainer_state_to_out(session: TrainerSession) -> TrainerRuntimeStateOut:
    runtime_state = dict(session.runtime_state_json or {})
    raw_brief = runtime_state.get("scenario_brief") or session.scenario_spec_json or {}
    scenario_brief_out = ScenarioBriefOut(
        read_aloud_brief=str(raw_brief.get("read_aloud_brief") or ""),
        environment=str(raw_brief.get("environment") or ""),
        location_overview=str(raw_brief.get("location_overview") or ""),
        threat_context=str(raw_brief.get("threat_context") or ""),
        evacuation_options=_join_if_list(raw_brief.get("evacuation_options", "")),
        evacuation_time=str(raw_brief.get("evacuation_time") or ""),
        special_considerations=_join_if_list(raw_brief.get("special_considerations", "")),
    )
    return TrainerRuntimeStateOut(
        simulation_id=session.simulation_id,
        session_id=session.id,
        status=session.status,
        state_revision=int(runtime_state.get("state_revision", 0) or 0),
        active_elapsed_seconds=int(runtime_state.get("active_elapsed_seconds", 0) or 0),
        scenario_brief=scenario_brief_out,
        current_snapshot=TrainerRuntimeSnapshotOut.model_validate(
            runtime_state.get("current_snapshot") or {}
        ),
        ai_plan=RuntimeInstructorIntent.model_validate(runtime_state.get("ai_plan") or {}),
        ai_rationale_notes=list(runtime_state.get("ai_rationale_notes") or []),
        pending_runtime_reasons=list(runtime_state.get("pending_runtime_reasons") or []),
        currently_processing_reasons=list(runtime_state.get("currently_processing_reasons") or []),
        last_runtime_error=str(runtime_state.get("last_runtime_error") or ""),
        last_ai_tick_at=session.last_ai_tick_at,
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
