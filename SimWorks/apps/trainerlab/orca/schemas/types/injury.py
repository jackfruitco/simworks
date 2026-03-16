# trainerlab/orca/types/injury.py
from typing import Literal

from pydantic import Field, field_validator

from apps.trainerlab.injury_dictionary import (
    normalize_injury_category,
    normalize_injury_kind,
    normalize_injury_location,
)
from apps.trainerlab.models import Injury as ORMInjury
from orchestrai_django.types import StrictBaseModel

__all__ = ["Illness", "Injury"]


class Injury(StrictBaseModel):
    """LLM-facing schema for an injury cause.

    Maps to trainerlab.Injury (immutable cause record).
    Problem-level fields (march_category, severity) are also provided here
    and consumed by post_persist() to create the associated Problem record.
    The auto-mapper creates the Injury ORM object; extra fields are silently
    ignored when writing to the DB.
    """

    kind: Literal["injury"] = Field(..., description="Discriminator — always 'injury'")
    injury_location: ORMInjury.InjuryLocation = Field(..., description="Anatomic location")
    injury_kind: ORMInjury.InjuryKind = Field(..., description="Mechanism of injury")
    injury_description: str = Field(..., max_length=100, description="Brief description")
    march_category: str = Field(..., description="MARCH triage category (M, A, R, C, H1, H2, PC)")
    severity: Literal["low", "moderate", "high", "critical"] = Field(
        default="moderate", description="Problem severity"
    )

    __orm_model__ = "trainerlab.Injury"

    @field_validator("march_category", mode="before")
    @classmethod
    def _normalize_march_category(cls, value):
        return normalize_injury_category(value)

    @field_validator("injury_location", mode="before")
    @classmethod
    def _normalize_injury_location(cls, value):
        return normalize_injury_location(value)

    @field_validator("injury_kind", mode="before")
    @classmethod
    def _normalize_injury_kind(cls, value):
        return normalize_injury_kind(value)


class Illness(StrictBaseModel):
    """LLM-facing schema for an illness cause.

    Maps to trainerlab.Illness (immutable cause record).
    Problem-level fields (march_category, severity) are consumed by
    post_persist() to create the associated Problem record.
    """

    kind: Literal["illness"] = Field(..., description="Discriminator — always 'illness'")
    name: str = Field(..., max_length=120, description="Illness name")
    description: str = Field(default="", max_length=500, description="Brief description")
    march_category: str = Field(
        ..., description="MARCH triage category this illness maps to (R, C, etc.)"
    )
    severity: Literal["low", "moderate", "high", "critical"] = Field(
        default="moderate", description="Problem severity"
    )

    __orm_model__ = "trainerlab.Illness"

    @field_validator("march_category", mode="before")
    @classmethod
    def _normalize_march_category(cls, value):
        return normalize_injury_category(value)
