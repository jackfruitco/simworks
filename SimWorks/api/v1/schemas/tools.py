"""Tool schemas for API v1."""

from typing import Literal

from pydantic import BaseModel, Field

from api.v1.schemas.lab_orders import LabOrderItem, lab_order_list_field


class ToolDataItemBase(BaseModel):
    """Base schema for typed tool payload items."""

    kind: str = Field(..., description="Discriminator for the tool payload item")
    db_pk: int | None = Field(default=None, description="Primary key of the backing metadata row")


class SimulationMetadataItem(ToolDataItemBase):
    kind: Literal["patient_demographics"] = "patient_demographics"
    key: str = Field(..., description="Metadata field key")
    value: str = Field(..., description="Metadata field value")


class AssessmentRubricRefItem(BaseModel):
    """Compact rubric reference embedded in :class:`AssessmentToolItem`."""

    slug: str = Field(..., description="Rubric slug")
    version: int = Field(..., description="Rubric version")
    name: str = Field(..., description="Human-readable rubric name")


class AssessmentCriterionScoreItem(BaseModel):
    """One criterion result within an assessment tool payload."""

    slug: str = Field(..., description="Criterion slug")
    label: str = Field(..., description="Human-readable criterion label")
    value: bool | int | float | str | None = Field(
        ...,
        description=(
            "Typed criterion value (bool / int / decimal / text / enum / json). "
            "May be null when the criterion did not produce a typed value."
        ),
    )
    score: float | None = Field(
        default=None,
        description="Normalized 0..1 score, if computed.",
    )
    rationale: str = Field(default="", description="Optional rationale text.")
    evidence: list[dict] = Field(
        default_factory=list,
        description=(
            "Evidence references; see assessments.AssessmentCriterionScore.evidence help_text."
        ),
    )


class AssessmentCriterionGroupItem(BaseModel):
    """Criteria grouped by their ``category`` (empty string for ungrouped)."""

    category: str = Field(..., description="Criterion category (empty string allowed).")
    criteria: list[AssessmentCriterionScoreItem]


class AssessmentToolItem(ToolDataItemBase):
    kind: Literal["simulation_assessment"] = "simulation_assessment"
    assessment_id: str = Field(..., description="Assessment UUID as a string")
    assessment_type: str = Field(..., description="e.g. 'initial_feedback'")
    lab_type: str = Field(..., description="e.g. 'chatlab'")
    rubric: AssessmentRubricRefItem
    overall_summary: str = Field(default="")
    overall_score: float | None = Field(
        default=None, description="Normalized 0..1 overall score, if computed."
    )
    groups: list[AssessmentCriterionGroupItem]


class PatientHistoryItem(ToolDataItemBase):
    kind: Literal["patient_history"] = "patient_history"
    key: str = Field(..., description="Diagnosis key")
    value: str = Field(..., description="Diagnosis details")
    diagnosis: str = Field(..., description="Diagnosis name")
    is_resolved: bool = Field(..., description="Whether the condition is resolved")
    duration: str = Field(..., description="How long the history item has been present")
    summary: str = Field(..., description="Human-readable history summary")


class LabResultItem(ToolDataItemBase):
    kind: Literal["lab_result"] = "lab_result"
    key: str = Field(..., description="Lab result key")
    result_name: str = Field(..., description="Lab result name")
    panel_name: str | None = Field(default=None, description="Lab panel name")
    value: str = Field(..., description="Lab result value")
    unit: str | None = Field(default=None, description="Lab result unit")
    reference_range_high: str | None = Field(default=None, description="Upper reference range")
    reference_range_low: str | None = Field(default=None, description="Lower reference range")
    flag: str = Field(..., description="Result flag")
    attribute: str = Field(..., description="Model attribute label")
    type: str = Field(..., description="Result type")


type ToolDataItem = SimulationMetadataItem | AssessmentToolItem | PatientHistoryItem | LabResultItem


class ToolOut(BaseModel):
    """Output schema for a simulation tool payload."""

    name: str = Field(..., description="Tool slug")
    display_name: str = Field(..., description="Human-readable tool name")
    data: list[ToolDataItem] = Field(default_factory=list, description="Tool-specific data")
    is_generic: bool = Field(default=False, description="Whether this is a generic key-value tool")
    checksum: str = Field(..., description="Checksum for client cache validation")


class ToolListResponse(BaseModel):
    """Response for listing tool payloads."""

    items: list[ToolOut] = Field(..., description="Tool payloads")


class SignOrdersIn(BaseModel):
    """Input schema for lab order signing."""

    submitted_orders: list[LabOrderItem] = lab_order_list_field(
        description="Lab orders to sign and enqueue. Maximum 50 orders per request."
    )
