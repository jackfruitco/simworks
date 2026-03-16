# trainerlab/orca/schemas/runtime.py

from typing import Literal

from pydantic import Field, model_validator

from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem
from apps.trainerlab.schemas import RuntimeInstructorIntent, RuntimePatientStatus
from orchestrai.types import StrictBaseModel


class RuntimeConditionChange(StrictBaseModel):
    action: Literal["create", "update", "resolve"]
    condition_kind: Literal["injury", "illness"]
    # target_event_id references a Problem ID (not Injury/Illness) for update/resolve.
    target_event_id: int | None = None

    # Injury-specific cause fields (create/update)
    injury_location: str | None = None
    injury_kind: str | None = None
    injury_description: str | None = None

    # Illness-specific cause fields (create/update)
    name: str | None = None
    description: str | None = None

    # Problem-level fields (create/update)
    march_category: str | None = None
    severity: Literal["low", "moderate", "high", "critical"] | None = None

    @model_validator(mode="after")
    def validate_shape(self):
        if self.action in {"update", "resolve"} and self.target_event_id is None:
            raise ValueError("target_event_id is required for update/resolve changes")
        if self.condition_kind == "injury" and self.action != "resolve":
            required = [self.injury_location, self.injury_kind]
            if any(value in (None, "") for value in required):
                raise ValueError("injury_location and injury_kind are required")
            if not self.injury_description:
                raise ValueError("injury_description is required for injury changes")
            if not self.march_category:
                raise ValueError("march_category is required for injury changes")
        if self.condition_kind == "illness" and self.action != "resolve":
            if not self.name:
                raise ValueError("name is required for illness changes")
            if self.severity is None:
                raise ValueError("severity is required for illness changes")
            if not self.march_category:
                raise ValueError("march_category is required for illness changes")
        return self


class RuntimeVitalChange(StrictBaseModel):
    action: Literal["update"] = "update"
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


class RuntimeInterventionEffectChange(StrictBaseModel):
    action: Literal["record"] = "record"
    intervention_event_id: int
    status: Literal["active", "effective", "ineffective", "resolved"] = "active"
    clinical_effect: str = ""
    notes: str = ""


class RuntimeStateChanges(StrictBaseModel):
    conditions: list[RuntimeConditionChange] = Field(default_factory=list)
    vitals: list[RuntimeVitalChange] = Field(default_factory=list)
    interventions: list[RuntimeInterventionEffectChange] = Field(default_factory=list)


class RuntimeSnapshotCondition(StrictBaseModel):
    domain_event_id: int | None = None
    kind: Literal["injury", "illness", "other"]
    label: str
    status: Literal["active", "resolved", "worsening", "improving", "stable"] = "active"
    march_category: str | None = None
    injury_location: str | None = None
    injury_kind: str | None = None
    description: str = ""
    severity: str | None = None


class RuntimeSnapshotIntervention(StrictBaseModel):
    domain_event_id: int | None = None
    intervention_type: str | None = None
    site_code: str | None = None
    effectiveness: str = "unknown"
    notes: str = ""
    code: str = ""
    description: str = ""
    target: str = ""
    anatomic_location: str = ""
    performed_by_role: Literal["trainee", "instructor", "ai"] = "trainee"
    status: Literal["active", "effective", "ineffective", "resolved"] = "active"
    clinical_effect: str = ""


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
    conditions: list[RuntimeSnapshotCondition] = Field(default_factory=list)
    interventions: list[RuntimeSnapshotIntervention] = Field(default_factory=list)
    vitals: list[RuntimeSnapshotVital] = Field(default_factory=list)
    patient_status: RuntimePatientStatus = Field(default_factory=RuntimePatientStatus)


class TrainerRuntimeTurnOutput(StrictBaseModel):
    state_changes: RuntimeStateChanges = Field(default_factory=RuntimeStateChanges)
    snapshot: TrainerRuntimeSnapshot
    instructor_intent: RuntimeInstructorIntent = Field(default_factory=RuntimeInstructorIntent)
    rationale_notes: list[str] = Field(default_factory=list)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)
