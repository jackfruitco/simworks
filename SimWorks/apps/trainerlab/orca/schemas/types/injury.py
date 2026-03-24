# trainerlab/orca/types/injury.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, Field, model_validator
from slugify import slugify

from apps.trainerlab.cause_dictionary import normalize_cause_kind
from apps.trainerlab.diagnostic_dictionary import (
    get_diagnostic_definition,
    normalize_diagnostic_kind,
)
from apps.trainerlab.finding_dictionary import get_finding_definition, normalize_finding_kind
from apps.trainerlab.injury_dictionary import (
    normalize_injury_category,
    normalize_injury_kind,
    normalize_injury_location,
)
from apps.trainerlab.intervention_dictionary import normalize_intervention_type
from apps.trainerlab.problem_dictionary import get_problem_definition, normalize_problem_kind
from orchestrai_django.types import StrictBaseModel

__all__ = [
    "AssessmentFindingSeed",
    "DiagnosticResultSeed",
    "DispositionStateSeed",
    "IllnessSeed",
    "InjurySeed",
    "PerformedInterventionSeed",
    "ProblemSeed",
    "RecommendedInterventionSeed",
    "ResourceStateSeed",
]


def _normalized_slug(value: str) -> str:
    return slugify(value or "", separator="_")


def _normalized_code(value: str) -> str:
    return _normalized_slug(value).upper()


class CauseSeedBase(StrictBaseModel):
    temp_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("temp_id", "external_id"),
        serialization_alias="temp_id",
    )
    cause_kind: str
    kind: str = Field(..., description="Canonical normalized cause kind slug")
    code: str = Field(..., description="Canonical normalized cause code")
    title: str = Field(..., description="UI-facing cause title")
    display_name: str = ""
    description: str = ""
    anatomical_location: str = ""
    laterality: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_shared_fields(self):
        self.cause_kind = normalize_cause_kind(self.cause_kind)
        if not self.display_name:
            self.display_name = self.title
        if not self.kind:
            self.kind = _normalized_slug(self.code or self.title)
        if not self.code:
            self.code = _normalized_code(self.kind or self.title)
        return self


class InjurySeed(CauseSeedBase):
    cause_kind: Literal["injury"] = "injury"
    injury_location: str = Field(..., description="Canonical anatomic injury location code")
    injury_kind: str = Field(..., description="Canonical injury mechanism code")
    injury_description: str = Field(..., max_length=500)

    @model_validator(mode="after")
    def _normalize_injury_fields(self):
        self.injury_location = normalize_injury_location(self.injury_location)
        self.injury_kind = normalize_injury_kind(self.injury_kind or self.code or self.title)
        self.code = self.injury_kind
        if not self.kind:
            self.kind = _normalized_slug(self.injury_kind)
        if not self.title:
            self.title = self.injury_description
        if not self.display_name:
            self.display_name = self.title
        if not self.description:
            self.description = self.injury_description
        if not self.anatomical_location:
            self.anatomical_location = self.injury_location
        return self


class IllnessSeed(CauseSeedBase):
    cause_kind: Literal["illness"] = "illness"
    name: str = Field(
        ...,
        max_length=120,
        validation_alias=AliasChoices("name", "illness_name"),
        serialization_alias="name",
    )

    @model_validator(mode="after")
    def _normalize_illness_fields(self):
        if not self.title:
            self.title = self.name
        if not self.display_name:
            self.display_name = self.title
        if not self.kind:
            self.kind = _normalized_slug(self.name)
        if not self.code:
            self.code = _normalized_code(self.name)
        return self


class ProblemSeed(StrictBaseModel):
    temp_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("temp_id", "external_id"),
        serialization_alias="temp_id",
    )
    kind: str = Field(
        ...,
        validation_alias=AliasChoices("problem_kind", "kind"),
        serialization_alias="kind",
    )
    code: str = Field(
        default="",
        validation_alias=AliasChoices("canonical_code", "code"),
        serialization_alias="code",
    )
    title: str = Field(..., validation_alias=AliasChoices("title", "display_label"))
    display_name: str = ""
    description: str = ""
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    march_category: str | None = None
    anatomical_location: str = ""
    laterality: str = ""
    cause_ref: str
    recommendation_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Canonical cross-references to recommended_interventions[*].temp_id values only. "
            "Do not use labels, titles, or aliases here."
        ),
    )
    initial_status: Literal["active", "treated", "controlled", "resolved"] = "active"

    @model_validator(mode="after")
    def _normalize_problem_fields(self):
        definition = get_problem_definition(self.kind or self.code or self.title)
        self.kind = normalize_problem_kind(definition.kind)
        if not self.code:
            self.code = definition.code
        if not self.display_name:
            self.display_name = self.title
        if self.march_category:
            self.march_category = normalize_injury_category(self.march_category)
        elif definition.default_march_category:
            self.march_category = definition.default_march_category
        return self


class RecommendedInterventionSeed(StrictBaseModel):
    temp_id: str = Field(
        ...,
        min_length=1,
        description="Canonical temp_id used by problems[*].recommendation_refs.",
        validation_alias=AliasChoices("temp_id", "external_id"),
        serialization_alias="temp_id",
    )
    intervention_kind: str = Field(
        ...,
        validation_alias=AliasChoices("intervention_kind", "kind", "code", "canonical_code"),
        serialization_alias="intervention_kind",
    )
    title: str = Field(default="", validation_alias=AliasChoices("title", "display_label"))
    target_problem_ref: str
    target_cause_ref: str | None = None
    rationale: str = ""
    priority: int | None = Field(default=None, ge=1, le=5)
    site: str = Field(default="", validation_alias=AliasChoices("site", "location"))
    contraindications: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_recommendation_seed(self):
        self.intervention_kind = (self.intervention_kind or self.title).strip()
        if not self.title:
            self.title = self.intervention_kind
        return self


class AssessmentFindingSeed(StrictBaseModel):
    temp_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("temp_id", "external_id"),
        serialization_alias="temp_id",
    )
    finding_kind: str = Field(
        ...,
        validation_alias=AliasChoices("finding_kind", "kind", "code"),
        serialization_alias="finding_kind",
    )
    title: str = Field(default="", validation_alias=AliasChoices("title", "display_label"))
    description: str = ""
    status: Literal["present", "stable", "improving", "worsening"] = "present"
    severity: Literal["low", "moderate", "high", "critical"] = "moderate"
    target_problem_ref: str | None = None
    anatomical_location: str = ""
    laterality: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_finding_seed(self):
        definition = get_finding_definition(self.finding_kind)
        self.finding_kind = normalize_finding_kind(definition.kind)
        if not self.title:
            self.title = definition.title
        return self


class DiagnosticResultSeed(StrictBaseModel):
    temp_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("temp_id", "external_id"),
        serialization_alias="temp_id",
    )
    diagnostic_kind: str = Field(
        ...,
        validation_alias=AliasChoices("diagnostic_kind", "kind", "code"),
        serialization_alias="diagnostic_kind",
    )
    title: str = Field(default="", validation_alias=AliasChoices("title", "display_label"))
    description: str = ""
    status: Literal["pending", "available", "reviewed"] = "pending"
    value_text: str = ""
    target_problem_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_diagnostic_seed(self):
        definition = get_diagnostic_definition(self.diagnostic_kind)
        self.diagnostic_kind = normalize_diagnostic_kind(definition.kind)
        if not self.title:
            self.title = definition.title
        return self


class ResourceStateSeed(StrictBaseModel):
    temp_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("temp_id", "external_id"),
        serialization_alias="temp_id",
    )
    kind: str = Field(..., validation_alias=AliasChoices("resource_kind", "kind", "code"))
    code: str = ""
    title: str = ""
    display_name: str = ""
    status: Literal["available", "limited", "depleted", "unavailable"] = "available"
    quantity_available: int = 0
    quantity_unit: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_resource_seed(self):
        self.kind = _normalized_slug(self.kind or self.code or self.title)
        if not self.code:
            self.code = self.kind
        if not self.title:
            self.title = self.display_name or self.kind.replace("_", " ").title()
        if not self.display_name:
            self.display_name = self.title
        return self


class DispositionStateSeed(StrictBaseModel):
    status: Literal["hold", "ready", "en_route", "delayed", "complete"] = "hold"
    transport_mode: str = ""
    destination: str = ""
    eta_minutes: int | None = None
    handoff_ready: bool = False
    scene_constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PerformedInterventionSeed(StrictBaseModel):
    intervention_kind: str = Field(
        ...,
        validation_alias=AliasChoices("intervention_kind", "kind", "code", "canonical_code"),
        serialization_alias="intervention_kind",
    )
    target_problem_ref: str
    site: str = Field(default="", validation_alias=AliasChoices("site", "location"))
    title: str = ""
    notes: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    initiated_by_type: Literal["user", "instructor", "system"] = "system"
    initiated_by_id: int | None = None

    @model_validator(mode="after")
    def _normalize_performed_kind(self):
        self.intervention_kind = normalize_intervention_type(self.intervention_kind or self.title)
        return self
