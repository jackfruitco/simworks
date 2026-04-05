"""TrainerLab API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.common.retries import has_user_retries_remaining
from apps.trainerlab.injury_dictionary import (
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
    DebriefAnnotation,
    ScenarioInstruction,
    ScenarioInstructionPermission,
    TrainerSession,
)
from apps.trainerlab.schemas import RuntimeInstructorIntent, RuntimePatientStatus
from apps.trainerlab.viewmodels import (
    build_runtime_snapshot,
    build_trainer_rest_view_model,
    load_trainer_engine_aggregate,
)


class LabAccessOut(BaseModel):
    lab_slug: str


class TrainerSessionCreateIn(BaseModel):
    scenario_spec: dict[str, Any] = Field(default_factory=dict)
    directives: str | None = None
    modifiers: list[str] = Field(default_factory=list)


class TrainerRunOut(BaseModel):
    simulation_id: int
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    scenario_spec: dict[str, Any]
    initial_directives: str | None
    tick_interval_seconds: int
    run_started_at: datetime | None
    run_paused_at: datetime | None
    run_completed_at: datetime | None
    last_ai_tick_at: datetime | None
    created_at: datetime
    modified_at: datetime
    terminal_reason_code: str | None = None
    terminal_reason_text: str | None = None
    retryable: bool | None = None


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
    injury_location: str = Field(
        ...,
        description="Injury location code or friendly label (normalized to canonical code)",
    )
    injury_kind: str = Field(
        ...,
        description="Injury kind code or friendly label (normalized to canonical code)",
    )
    injury_description: str = Field(..., max_length=500)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = Field(
        default=None,
        description="ID of the Injury being superseded by this new cause record",
    )

    @field_validator("injury_location")
    @classmethod
    def _normalize_injury_location(cls, value: str) -> str:
        return normalize_injury_location(value)

    @field_validator("injury_kind")
    @classmethod
    def _normalize_injury_kind(cls, value: str) -> str:
        return normalize_injury_kind(value)


class IllnessCreateIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(validation_alias=AliasChoices("illness_name", "name"))
    description: str = Field(
        default="", validation_alias=AliasChoices("illness_description", "description")
    )
    anatomical_location: str = ""
    laterality: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = Field(
        default=None,
        description="ID of the Illness being superseded by this new cause record",
    )


class ProblemCreateIn(BaseModel):
    cause_kind: Literal["injury", "illness"]
    cause_id: int
    parent_problem_id: int | None = None
    kind: str
    code: str | None = None
    title: str = Field(min_length=1, max_length=120)
    display_name: str = ""
    description: str = ""
    march_category: str = Field(
        ...,
        description="MARCH triage category code (M, A, R, C, H1, H2, PC)",
    )
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    anatomical_location: str = ""
    laterality: str = ""
    status: Literal["active", "treated", "controlled", "resolved"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = Field(
        default=None,
        description="ID of the Problem being superseded by this new problem record",
    )

    @field_validator("march_category")
    @classmethod
    def _normalize_problem_march_category(cls, value: str) -> str:
        from apps.trainerlab.injury_dictionary import normalize_injury_category

        return normalize_injury_category(value)

    @field_validator("kind")
    @classmethod
    def _normalize_problem_kind(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("kind must not be blank")
        return normalized

    @field_validator("code")
    @classmethod
    def _normalize_problem_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "_")
        return normalized or None

    @model_validator(mode="after")
    def _default_problem_code(self) -> "ProblemCreateIn":
        self.code = self.code or self.kind
        if not self.display_name:
            self.display_name = self.title
        return self


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
    target_problem_id: int
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
    initiated_by_type: Literal["user", "instructor", "system"] = "user"
    initiated_by_id: int | None = None
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
    performed_by_role: Literal["trainee", "instructor", "system"] = "instructor"

    @field_validator("content")
    @classmethod
    def _normalize_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class AssessmentFindingCreateIn(BaseModel):
    finding_kind: str
    title: str = ""
    description: str = ""
    status: Literal["present", "stable", "improving", "worsening"] = "present"
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    target_problem_id: int | None = None
    anatomical_location: str = ""
    laterality: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class DiagnosticResultCreateIn(BaseModel):
    diagnostic_kind: str
    title: str = ""
    description: str = ""
    status: Literal["pending", "available", "reviewed"] = "pending"
    value_text: str = ""
    target_problem_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class ResourceStateCreateIn(BaseModel):
    kind: str
    code: str | None = None
    title: str
    display_name: str = ""
    status: Literal["available", "limited", "depleted", "unavailable"] = "available"
    quantity_available: int = 0
    quantity_unit: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class DispositionStateCreateIn(BaseModel):
    status: Literal["hold", "ready", "en_route", "delayed", "complete"] = "hold"
    transport_mode: str = ""
    destination: str = ""
    eta_minutes: int | None = None
    handoff_ready: bool = False
    scene_constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


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


class RuntimeCauseStateOut(BaseModel):
    id: int
    active: bool = True
    cause_kind: Literal["injury", "illness"]
    kind: str
    code: str
    slug: str | None = None
    title: str
    display_name: str | None = None
    description: str | None = None
    anatomical_location: str | None = None
    laterality: str | None = None
    recommended_interventions: list["RecommendedInterventionStateOut"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    timestamp: str | None = None


class RecommendedInterventionStateOut(BaseModel):
    recommendation_id: int
    active: bool = True
    kind: str
    code: str
    slug: str | None = None
    title: str
    display_name: str | None = None
    description: str | None = None
    target_problem_id: int
    target_cause_id: int | None = None
    target_cause_kind: Literal["injury", "illness"] | None = None
    recommendation_source: Literal["ai", "rules", "merged"]
    validation_status: Literal["accepted", "normalized", "downgraded", "rejected"]
    normalized_kind: str
    normalized_code: str
    rationale: str = ""
    priority: int | None = None
    site_code: str | None = None
    site_label: str | None = None
    warnings: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeProblemStateOut(BaseModel):
    problem_id: int
    active: bool = True
    kind: str
    code: str
    slug: str | None = None
    title: str
    display_name: str | None = None
    description: str | None = None
    severity: str | None = None
    march_category: str | None = None
    anatomical_location: str | None = None
    laterality: str | None = None
    status: Literal["active", "treated", "controlled", "resolved"]
    previous_status: str | None = None
    treated_at: str | None = None
    controlled_at: str | None = None
    resolved_at: str | None = None
    cause_id: int
    cause_kind: Literal["injury", "illness"]
    parent_problem_id: int | None = None
    triggering_intervention_id: int | None = None
    adjudication_reason: str = ""
    adjudication_rule_id: str = ""
    recommended_interventions: list[RecommendedInterventionStateOut] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    timestamp: str | None = None

    @field_validator("previous_status", mode="before")
    @classmethod
    def normalize_previous_status(cls, v: object) -> str | None:
        _VALID = {"active", "treated", "controlled", "resolved"}
        if isinstance(v, str) and v in _VALID:
            return v
        return None


class RuntimeInterventionStateOut(BaseModel):
    intervention_id: int
    active: bool = True
    kind: str
    code: str
    title: str
    site_code: str | None = None
    effectiveness: str = "unknown"
    notes: str = ""
    description: str = ""
    target_problem_id: int | None = None
    initiated_by_type: Literal["user", "instructor", "system"]
    initiated_by_id: int | None = None
    status: str = "active"
    clinical_effect: str = ""
    target_problem_previous_status: str = ""
    target_problem_current_status: str = ""
    adjudication_reason: str = ""
    adjudication_rule_id: str = ""
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


class RuntimeAssessmentFindingStateOut(BaseModel):
    finding_id: int
    active: bool = True
    kind: str
    code: str
    slug: str | None = None
    title: str
    display_name: str | None = None
    description: str | None = None
    status: str
    severity: str | None = None
    target_problem_id: int | None = None
    anatomical_location: str | None = None
    laterality: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    timestamp: str | None = None


class RuntimeDiagnosticResultStateOut(BaseModel):
    diagnostic_id: int
    active: bool = True
    kind: str
    code: str
    slug: str | None = None
    title: str
    display_name: str | None = None
    description: str | None = None
    status: str
    value_text: str = ""
    target_problem_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    timestamp: str | None = None


class RuntimeResourceStateOut(BaseModel):
    resource_id: int
    active: bool = True
    kind: str
    code: str
    slug: str | None = None
    title: str
    display_name: str | None = None
    status: str
    quantity_available: int = 0
    quantity_unit: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    timestamp: str | None = None


class RuntimeDispositionStateOut(BaseModel):
    disposition_id: int
    active: bool = True
    status: str
    transport_mode: str = ""
    destination: str = ""
    eta_minutes: int | None = None
    handoff_ready: bool = False
    scene_constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    timestamp: str | None = None


class ScenarioBriefOut(BaseModel):
    read_aloud_brief: str = ""
    environment: str = ""
    location_overview: str = ""
    threat_context: str = ""
    evacuation_options: list[str] = Field(default_factory=list)
    evacuation_time: str = ""
    special_considerations: list[str] = Field(default_factory=list)


class ControlPlaneDebugOut(BaseModel):
    execution_plan: list[str] = Field(default_factory=list)
    current_step_index: int = 0
    queued_reasons: list[dict[str, Any]] = Field(default_factory=list)
    currently_processing_reasons: list[dict[str, Any]] = Field(default_factory=list)
    last_processed_reasons: list[dict[str, Any]] = Field(default_factory=list)
    last_failed_step: str = ""
    last_failed_error: str = ""
    last_patch_evaluation_summary: dict[str, Any] = Field(default_factory=dict)
    last_rejected_or_normalized_summary: dict[str, Any] = Field(default_factory=dict)
    status_flags: dict[str, Any] = Field(default_factory=dict)


class SnapshotCacheStatusOut(BaseModel):
    status: str = "disabled"
    authoritative: bool = False
    source: str = "disabled"
    state_revision: int | None = None


class EventTimelineEntryOut(BaseModel):
    event_id: str
    event_type: str
    created_at: datetime
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventTimelineOut(BaseModel):
    """RuntimeEvent-backed event read model for /state/ in this phase."""

    events: list[EventTimelineEntryOut] = Field(default_factory=list)
    total_events: int = 0


class ScenarioSnapshotOut(BaseModel):
    causes: list[RuntimeCauseStateOut] = Field(default_factory=list)
    problems: list[RuntimeProblemStateOut] = Field(default_factory=list)
    recommended_interventions: list[RecommendedInterventionStateOut] = Field(default_factory=list)
    interventions: list[RuntimeInterventionStateOut] = Field(default_factory=list)
    assessment_findings: list[RuntimeAssessmentFindingStateOut] = Field(default_factory=list)
    diagnostic_results: list[RuntimeDiagnosticResultStateOut] = Field(default_factory=list)
    resources: list[RuntimeResourceStateOut] = Field(default_factory=list)
    disposition: RuntimeDispositionStateOut | None = None
    vitals: list[RuntimeVitalStateOut] = Field(default_factory=list)
    pulses: list[dict[str, Any]] = Field(default_factory=list)
    patient_status: RuntimePatientStatus = Field(default_factory=RuntimePatientStatus)
    scenario_brief: ScenarioBriefOut | None = None


class RuntimeSnapshotOut(BaseModel):
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    phase: str = ""
    state_revision: int = 0
    active_elapsed_seconds: int = 0
    tick_count: int = 0
    tick_interval_seconds: int = 15
    next_tick_at: datetime | None = None
    runtime_processing: bool = False
    pending_runtime_reasons: list[dict[str, Any]] = Field(default_factory=list)
    currently_processing_reasons: list[dict[str, Any]] = Field(default_factory=list)
    ai_plan: RuntimeInstructorIntent = Field(default_factory=RuntimeInstructorIntent)
    ai_rationale_notes: list[str] = Field(default_factory=list)
    llm_conditions_check: list[dict[str, Any]] = Field(default_factory=list)
    last_runtime_error: str = ""
    last_ai_tick_at: datetime | None = None
    last_runtime_enqueued_at: str | None = None
    last_runtime_completed_at: str | None = None
    control_plane_debug: ControlPlaneDebugOut = Field(default_factory=ControlPlaneDebugOut)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    latest_event_cursor: str | None = Field(
        default=None,
        description=(
            "Cursor (UUID) of the most recent outbox event for this simulation. "
            "Pass this value as the `cursor` parameter when connecting to the "
            "SSE stream so only events created after this point are delivered. "
            "`null` when no events exist yet."
        ),
    )


class TrainerRestMetadataOut(BaseModel):
    builder_version: str = "v1"
    schema_version: str = "v1"
    snapshot_cache: SnapshotCacheStatusOut
    event_timeline_count: int = 0


class TrainerRestViewModelOut(BaseModel):
    simulation_id: int
    session_id: int
    status: Literal["seeding", "seeded", "running", "paused", "completed", "failed"]
    scenario_snapshot: ScenarioSnapshotOut
    runtime_snapshot: RuntimeSnapshotOut
    event_timeline: EventTimelineOut
    metadata: TrainerRestMetadataOut


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


class InterventionDictionaryItemOut(BaseModel):
    """iOS-compatible flat intervention dictionary item."""

    intervention_type: str
    label: str
    sites: list[DictionaryItemOut]


# ---------------------------------------------------------------------------
# #2 — Problem status control
# ---------------------------------------------------------------------------


class ProblemStatusUpdateIn(BaseModel):
    is_treated: bool | None = None
    is_resolved: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ProblemStatusUpdateIn":
        if self.is_treated is None and self.is_resolved is None:
            raise ValueError("At least one of is_treated or is_resolved must be provided.")
        return self


class ProblemStatusOut(BaseModel):
    problem_id: int
    is_treated: bool
    is_controlled: bool
    is_resolved: bool
    status: Literal["active", "treated", "controlled", "resolved"]
    label: str


# ---------------------------------------------------------------------------
# #4 — Debrief annotations
# ---------------------------------------------------------------------------


class AnnotationCreateIn(BaseModel):
    learning_objective: Literal[
        "assessment",
        "hemorrhage_control",
        "airway",
        "breathing",
        "circulation",
        "hypothermia",
        "communication",
        "triage",
        "intervention",
        "other",
    ] = "other"
    observation_text: str = Field(min_length=1, max_length=2000)
    outcome: Literal["correct", "incorrect", "missed", "improvised", "pending"] = "pending"
    linked_event_id: int | None = None
    elapsed_seconds_at: int | None = None


class AnnotationOut(BaseModel):
    id: int
    session_id: int
    simulation_id: int
    created_by_id: int | None
    learning_objective: str
    learning_objective_label: str
    observation_text: str
    outcome: str
    outcome_label: str
    linked_event_id: int | None
    elapsed_seconds_at: int | None
    created_at: datetime


def annotation_to_out(obj: DebriefAnnotation) -> AnnotationOut:
    return AnnotationOut(
        id=obj.id,
        session_id=obj.session_id,
        simulation_id=obj.simulation_id,
        created_by_id=obj.created_by_id,
        learning_objective=obj.learning_objective,
        learning_objective_label=obj.get_learning_objective_display(),
        observation_text=obj.observation_text,
        outcome=obj.outcome,
        outcome_label=obj.get_outcome_display(),
        linked_event_id=obj.linked_event_id,
        elapsed_seconds_at=obj.elapsed_seconds_at,
        created_at=obj.created_at,
    )


# ---------------------------------------------------------------------------
# #5 — Preset application diff
# ---------------------------------------------------------------------------


class PresetApplyCauseItem(BaseModel):
    id: int
    kind: str
    label: str


class PresetApplyVitalChange(BaseModel):
    before: dict[str, Any] | None
    after: dict[str, Any]


class PresetApplyDiff(BaseModel):
    causes_added: list[PresetApplyCauseItem] = Field(default_factory=list)
    vitals_changed: dict[str, PresetApplyVitalChange] = Field(default_factory=dict)
    state_revision_before: int | None = None


class PresetApplyOut(BaseModel):
    command_id: str
    status: str = "accepted"
    diff: PresetApplyDiff = Field(default_factory=PresetApplyDiff)


# ---------------------------------------------------------------------------
# #7 — Scenario brief edit
# ---------------------------------------------------------------------------


class ScenarioBriefUpdateIn(BaseModel):
    read_aloud_brief: str | None = None
    environment: str | None = None
    location_overview: str | None = None
    threat_context: str | None = None
    evacuation_options: list[str] | None = None
    evacuation_time: str | None = None
    special_considerations: list[str] | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ScenarioBriefUpdateIn":
        fields = [
            self.read_aloud_brief,
            self.environment,
            self.location_overview,
            self.threat_context,
            self.evacuation_options,
            self.evacuation_time,
            self.special_considerations,
        ]
        if all(f is None for f in fields):
            raise ValueError("At least one field must be provided to update the scenario brief.")
        return self


class ScenarioBriefDetailOut(BaseModel):
    domain_event_id: int
    read_aloud_brief: str
    environment: str
    location_overview: str
    threat_context: str
    evacuation_options: list[str]
    evacuation_time: str
    special_considerations: list[str]


def trainer_run_to_out(session: TrainerSession) -> TrainerRunOut:
    simulation = session.simulation
    terminal_reason_code = getattr(simulation, "terminal_reason_code", "") or None
    terminal_reason_text = getattr(simulation, "terminal_reason_text", "") or None
    retryable = None
    if terminal_reason_code:
        stored_retryable = (session.runtime_state_json or {}).get("initial_generation_retryable")
        if terminal_reason_code.startswith("trainerlab_initial_generation_"):
            if stored_retryable is None:
                retryable = has_user_retries_remaining(simulation.initial_retry_count)
            else:
                retryable = bool(stored_retryable) and has_user_retries_remaining(
                    simulation.initial_retry_count
                )
    return TrainerRunOut(
        simulation_id=session.simulation_id,
        status=session.status,
        scenario_spec=session.scenario_spec_json or {},
        initial_directives=session.initial_directives or None,
        tick_interval_seconds=session.tick_interval_seconds,
        run_started_at=session.run_started_at,
        run_paused_at=session.run_paused_at,
        run_completed_at=session.run_completed_at,
        last_ai_tick_at=session.last_ai_tick_at,
        created_at=session.created_at,
        modified_at=session.modified_at,
        terminal_reason_code=terminal_reason_code,
        terminal_reason_text=terminal_reason_text,
        retryable=retryable,
    )


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    return [str(value)]


def trainer_state_to_out(session: TrainerSession) -> TrainerRestViewModelOut:
    view_model = build_trainer_rest_view_model(
        load_trainer_engine_aggregate(session=session, include_latest_event_cursor=True)
    )
    return TrainerRestViewModelOut.model_validate(view_model.model_dump(mode="json"))


def control_plane_debug_to_out(session: TrainerSession) -> ControlPlaneDebugOut:
    aggregate = load_trainer_engine_aggregate(session=session)
    runtime_snapshot = build_runtime_snapshot(aggregate)
    debug = dict(runtime_snapshot.control_plane_debug or {})
    return ControlPlaneDebugOut.model_validate(
        {
            "execution_plan": list(debug.get("execution_plan") or []),
            "current_step_index": int(debug.get("current_step_index", 0) or 0),
            "queued_reasons": list(
                debug.get("queued_reasons") or runtime_snapshot.pending_runtime_reasons or []
            ),
            "currently_processing_reasons": list(
                debug.get("currently_processing_reasons")
                or runtime_snapshot.currently_processing_reasons
                or []
            ),
            "last_processed_reasons": list(debug.get("last_processed_reasons") or []),
            "last_failed_step": str(debug.get("last_failed_step") or ""),
            "last_failed_error": str(
                debug.get("last_failed_error") or runtime_snapshot.last_runtime_error or ""
            ),
            "last_patch_evaluation_summary": dict(debug.get("last_patch_evaluation") or {}),
            "last_rejected_or_normalized_summary": dict(
                debug.get("last_rejected_or_normalized") or {}
            ),
            "status_flags": dict(debug.get("status_flags") or {}),
        }
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


RuntimeCauseStateOut.model_rebuild()
