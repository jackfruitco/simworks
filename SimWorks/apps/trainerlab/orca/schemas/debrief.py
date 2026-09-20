# trainerlab/orca/schemas/debrief.py

from typing import Literal

from pydantic import Field

from orchestrai.types import StrictBaseModel


class DebriefClaim(StrictBaseModel):
    category: Literal["summary", "strength", "miss", "teaching_point", "assessment"]
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class TrainerRunDebriefOutput(StrictBaseModel):
    claims: list[DebriefClaim] = Field(default_factory=list, max_length=30)
