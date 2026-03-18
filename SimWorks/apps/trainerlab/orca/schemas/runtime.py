# trainerlab/orca/schemas/runtime.py

from typing import Literal

from pydantic import Field, model_validator

from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem
from apps.trainerlab.schemas import (
    AssessmentFindingState,
    DiagnosticResultState,
    DispositionStateSnapshot,
    ResourceStateSnapshot,
    RuntimeInstructorIntent,
    RuntimePatientStatus,
    ScenarioBrief,
)
from orchestrai.types import StrictBaseModel


class RuntimeProblemObservation(StrictBaseModel):
    worker_kind: str = ""
    domains: list[str] = Field(default_factory=list)
    driver_reason_kinds: list[str] = Field(default_factory=list)
    driver_intervention_ids: list[int] = Field(default_factory=list)
    source_call_id: str = ""
    correlation_id: str = ""
    observation: Literal[
        "new_problem",
        "worsening",
        "improving",
        "resolved_candidate",
        "stable",
    ] = "stable"
    target_problem_id: int | None = None
    cause_kind: Literal["injury", "illness"] | None = None
    cause_id: int | None = None
    parent_problem_id: int | None = None
    problem_kind: str
    title: str
    description: str = ""
    march_category: str | None = None
    severity: Literal["low", "moderate", "high", "critical"] | None = None
    anatomical_location: str | None = None
    laterality: str | None = None

    @model_validator(mode="after")
    def validate_shape(self):
        if self.observation == "new_problem":
            if self.cause_id is None or self.cause_kind is None:
                raise ValueError("new_problem observations require cause_id and cause_kind")
        elif self.target_problem_id is None:
            raise ValueError(
                "Existing-problem observations require target_problem_id unless creating a new problem"
            )
        return self


class RuntimeVitalUpdate(StrictBaseModel):
    worker_kind: str = ""
    domains: list[str] = Field(default_factory=list)
    driver_reason_kinds: list[str] = Field(default_factory=list)
    driver_intervention_ids: list[int] = Field(default_factory=list)
    source_call_id: str = ""
    correlation_id: str = ""
    vital_type: Literal[
        "heart_rate",
        "respiratory_rate",
        "spo2",
        "etco2",
        "blood_glucose",
        "blood_pressure",
    ]
    min_value: int = Field(..., gt=0)
    max_value: int = Field(..., gt=0)
    lock_value: bool = False
    min_value_diastolic: int | None = None
    max_value_diastolic: int | None = None
    trend: Literal["up", "down", "stable", "variable"] = "stable"

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_value > self.max_value:
            raise ValueError("min_value must be less than or equal to max_value")
        if self.vital_type == "blood_pressure":
            if self.min_value_diastolic is None or self.max_value_diastolic is None:
                raise ValueError("blood pressure updates require diastolic bounds")
            if self.min_value_diastolic > self.max_value_diastolic:
                raise ValueError("min_value_diastolic must be <= max_value_diastolic")
        return self


class RuntimePulseUpdate(StrictBaseModel):
    worker_kind: str = ""
    domains: list[str] = Field(default_factory=list)
    driver_reason_kinds: list[str] = Field(default_factory=list)
    driver_intervention_ids: list[int] = Field(default_factory=list)
    source_call_id: str = ""
    correlation_id: str = ""
    location: Literal[
        "radial_left",
        "radial_right",
        "femoral_left",
        "femoral_right",
        "carotid_left",
        "carotid_right",
        "pedal_left",
        "pedal_right",
    ]
    present: bool
    description: Literal["strong", "bounding", "weak", "absent", "thready"]
    color_normal: bool
    color_description: Literal["pink", "pale", "mottled", "cyanotic", "flushed"]
    condition_normal: bool
    condition_description: Literal["dry", "moist", "diaphoretic", "clammy"]
    temperature_normal: bool
    temperature_description: Literal["warm", "cool", "cold", "hot"]


class RuntimeVitalChange(RuntimeVitalUpdate):
    action: Literal["update"] = "update"


class RuntimePulseChange(RuntimePulseUpdate):
    action: Literal["update"] = "update"


class RuntimeFindingUpdate(StrictBaseModel):
    worker_kind: str = ""
    domains: list[str] = Field(default_factory=list)
    driver_reason_kinds: list[str] = Field(default_factory=list)
    driver_intervention_ids: list[int] = Field(default_factory=list)
    source_call_id: str = ""
    correlation_id: str = ""
    action: Literal["create", "update", "remove"] = "create"
    target_finding_id: int | None = None
    target_problem_id: int | None = None
    finding_kind: str
    title: str = ""
    description: str = ""
    status: Literal["present", "stable", "improving", "worsening"] = "present"
    severity: Literal["low", "moderate", "high", "critical"] | None = None
    anatomical_location: str = ""
    laterality: str = ""
    metadata: dict[str, str | int | float | bool | list[str] | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.action in {"update", "remove"} and self.target_finding_id is None:
            raise ValueError("target_finding_id is required for update/remove finding changes")
        return self


class RuntimeRecommendationSuggestion(StrictBaseModel):
    worker_kind: str = ""
    domains: list[str] = Field(default_factory=list)
    driver_reason_kinds: list[str] = Field(default_factory=list)
    driver_intervention_ids: list[int] = Field(default_factory=list)
    source_call_id: str = ""
    correlation_id: str = ""
    intervention_kind: str
    title: str = ""
    target_problem_id: int
    target_cause_id: int | None = None
    target_cause_kind: Literal["injury", "illness"] | None = None
    rationale: str = ""
    priority: int | None = None
    site: str = ""
    warnings: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool | list[str] | None] = Field(default_factory=dict)


class RuntimeInterventionAssessment(StrictBaseModel):
    worker_kind: str = ""
    domains: list[str] = Field(default_factory=list)
    driver_reason_kinds: list[str] = Field(default_factory=list)
    driver_intervention_ids: list[int] = Field(default_factory=list)
    source_call_id: str = ""
    correlation_id: str = ""
    intervention_event_id: int
    status: Literal["active", "effective", "ineffective", "resolved"] = "active"
    effectiveness: Literal[
        "unknown",
        "effective",
        "partially_effective",
        "ineffective",
    ] = "unknown"
    clinical_effect: str = ""
    notes: str = ""


class RuntimeStateChanges(StrictBaseModel):
    problem_observations: list[RuntimeProblemObservation] = Field(default_factory=list)
    vital_updates: list[RuntimeVitalUpdate] = Field(default_factory=list)
    pulse_updates: list[RuntimePulseUpdate] = Field(default_factory=list)
    finding_updates: list[RuntimeFindingUpdate] = Field(default_factory=list)
    recommendation_suggestions: list[RuntimeRecommendationSuggestion] = Field(default_factory=list)
    intervention_assessments: list[RuntimeInterventionAssessment] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _compatibility_aliases(cls, value):
        if isinstance(value, dict):
            payload = dict(value)
            if "pulses" in payload and "pulse_updates" not in payload:
                payload["pulse_updates"] = payload.pop("pulses")
            if "vitals" in payload and "vital_updates" not in payload:
                payload["vital_updates"] = payload.pop("vitals")
            return payload
        return value

    @property
    def pulses(self) -> list[RuntimePulseUpdate]:
        return self.pulse_updates

    @property
    def vitals(self) -> list[RuntimeVitalUpdate]:
        return self.vital_updates


class RuntimeSnapshotCause(StrictBaseModel):
    id: int | None = None
    cause_kind: Literal["injury", "illness"]
    kind: str
    code: str
    title: str
    description: str = ""
    anatomical_location: str = ""
    laterality: str = ""


class RuntimeSnapshotProblem(StrictBaseModel):
    problem_id: int | None = None
    kind: str
    code: str
    title: str
    description: str = ""
    status: Literal["active", "treated", "controlled", "resolved"] = "active"
    previous_status: str = ""
    march_category: str | None = None
    severity: Literal["low", "moderate", "high", "critical"] | None = None
    anatomical_location: str | None = None
    laterality: str | None = None
    cause_id: int | None = None
    cause_kind: Literal["injury", "illness"] | None = None
    parent_problem_id: int | None = None
    triggering_intervention_id: int | None = None
    adjudication_reason: str = ""
    adjudication_rule_id: str = ""


class RuntimeSnapshotRecommendedIntervention(StrictBaseModel):
    recommendation_id: int | None = None
    kind: str
    code: str
    title: str
    target_problem_id: int
    target_cause_id: int | None = None
    target_cause_kind: Literal["injury", "illness"] | None = None
    recommendation_source: Literal["ai", "rules", "merged"]
    validation_status: Literal["accepted", "normalized", "downgraded", "rejected"]
    normalized_kind: str
    normalized_code: str
    rationale: str = ""
    priority: int | None = None
    site_code: str = ""
    warnings: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)


class RuntimeSnapshotIntervention(StrictBaseModel):
    intervention_id: int | None = None
    intervention_type: str | None = None
    site_code: str | None = None
    effectiveness: str = "unknown"
    notes: str = ""
    target_problem_id: int | None = None
    initiated_by_type: Literal["user", "instructor", "system"] = "user"
    status: Literal["applied", "adjusted", "reassessed", "removed"] = "applied"
    clinical_effect: str = ""
    target_problem_previous_status: str = ""
    target_problem_current_status: str = ""
    adjudication_reason: str = ""
    adjudication_rule_id: str = ""


class RuntimeSnapshotPulse(StrictBaseModel):
    location: Literal[
        "radial_left",
        "radial_right",
        "femoral_left",
        "femoral_right",
        "carotid_left",
        "carotid_right",
        "pedal_left",
        "pedal_right",
    ]
    present: bool
    description: Literal["strong", "bounding", "weak", "absent", "thready"]
    color_normal: bool
    color_description: Literal["pink", "pale", "mottled", "cyanotic", "flushed"]
    condition_normal: bool
    condition_description: Literal["dry", "moist", "diaphoretic", "clammy"]
    temperature_normal: bool
    temperature_description: Literal["warm", "cool", "cold", "hot"]


class RuntimeSnapshotVital(StrictBaseModel):
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
    trend: Literal["up", "down", "stable", "variable"] = "stable"


class TrainerRuntimeSnapshot(StrictBaseModel):
    causes: list[RuntimeSnapshotCause] = Field(default_factory=list)
    problems: list[RuntimeSnapshotProblem] = Field(default_factory=list)
    recommended_interventions: list[RuntimeSnapshotRecommendedIntervention] = Field(
        default_factory=list
    )
    interventions: list[RuntimeSnapshotIntervention] = Field(default_factory=list)
    assessment_findings: list[AssessmentFindingState] = Field(default_factory=list)
    diagnostic_results: list[DiagnosticResultState] = Field(default_factory=list)
    resources: list[ResourceStateSnapshot] = Field(default_factory=list)
    disposition: DispositionStateSnapshot | None = None
    vitals: list[RuntimeSnapshotVital] = Field(default_factory=list)
    pulses: list[RuntimeSnapshotPulse] = Field(default_factory=list)
    patient_status: RuntimePatientStatus = Field(default_factory=RuntimePatientStatus)
    scenario_brief: ScenarioBrief | None = None


class TrainerRuntimeTurnOutput(StrictBaseModel):
    state_changes: RuntimeStateChanges = Field(default_factory=RuntimeStateChanges)
    patient_status: RuntimePatientStatus = Field(default_factory=RuntimePatientStatus)
    instructor_intent: RuntimeInstructorIntent = Field(default_factory=RuntimeInstructorIntent)
    rationale_notes: list[str] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)
