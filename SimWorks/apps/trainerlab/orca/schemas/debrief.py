# trainerlab/orca/schemas/debrief.py

from pydantic import BaseModel, ConfigDict, Field

from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem


class DebriefTimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    timestamp_label: str = Field(..., min_length=1)
    significance: str = Field(..., min_length=1)


class TrainerRunDebriefOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative_summary: str = Field(..., min_length=1)
    strengths: list[str] = Field(default_factory=list)
    misses: list[str] = Field(default_factory=list)
    deterioration_timeline: list[DebriefTimelineItem] = Field(default_factory=list)
    teaching_points: list[str] = Field(default_factory=list)
    overall_assessment: str = Field(..., min_length=1)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)
