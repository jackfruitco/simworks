# trainerlab/orca/types/injury.py
from typing import Literal

from pydantic import Field

from apps.trainerlab.models import Illness as ORMIllness, Injury as ORMInjury
from orchestrai_django.types import StrictBaseModel

__all__ = ["Illness", "Injury"]


class Injury(StrictBaseModel):
    """Pydantic model for Injury."""

    kind: Literal["injury"] = Field(..., description="Injury")
    injury_category: ORMInjury.InjuryCategory = Field(..., description="Category of the injury")
    injury_location: ORMInjury.InjuryLocation = Field(..., description="Location of the injury")
    injury_kind: ORMInjury.InjuryKind = Field(..., description="Kind of injury")

    injury_description: str = Field(..., max_length=100, description="Description of the injury")
    # parent_injury

    __orm_model__ = "trainerlab.Injury"


class Illness(StrictBaseModel):
    """Pydantic model for Illness."""

    kind: Literal["illness"] = Field(..., description="Illness")
    name: str = Field(..., max_length=120, description="Name of the illness")
    description: str = Field(..., max_length=100, description="Description of the illness")
    severity: ORMIllness.Severity = Field(..., description="Severity of the illness")

    __orm_model__ = "trainerlab.Illness"
