# trainerlab/orca/schemas/debrief.py

from pydantic import Field

from apps.simcore.orca.schemas.output_items import LLMConditionsCheckItem
from orchestrai.types import StrictBaseModel


class DebriefTimelineItem(StrictBaseModel):
    title: str = Field(..., min_length=1)
    timestamp_label: str = Field(..., min_length=1)
    significance: str = Field(..., min_length=1)


class TrainerRunDebriefOutput(StrictBaseModel):
    narrative_summary: str = Field(..., min_length=1)
    strengths: list[str] = Field(default_factory=list)
    misses: list[str] = Field(default_factory=list)
    deterioration_timeline: list[DebriefTimelineItem] = Field(default_factory=list)
    teaching_points: list[str] = Field(default_factory=list)
    overall_assessment: str = Field(..., min_length=1)
    llm_conditions_check: list[LLMConditionsCheckItem] = Field(default_factory=list)
