# trainerlab/orca/schemas/types/pulse.py
"""Pydantic schema types for pulse assessments."""

from typing import Literal

from pydantic import Field

from orchestrai_django.types import StrictBaseModel

__all__ = ["PulseAssessmentItem"]


class PulseAssessmentItem(StrictBaseModel):
    """Pulse assessment at a single anatomic site with laterality.

    Records pulse presence, quality description, and peripheral perfusion
    indicators (skin color, condition, temperature) for clinical realism.
    """

    location: Literal[
        "radial_left",
        "radial_right",
        "femoral_left",
        "femoral_right",
        "carotid_left",
        "carotid_right",
        "pedal_left",
        "pedal_right",
    ] = Field(..., description="Anatomic pulse site with laterality")

    present: bool = Field(..., description="Whether the pulse is palpable at this site")

    description: Literal["strong", "bounding", "weak", "absent", "thready"] = Field(
        ..., description="Pulse quality descriptor"
    )

    color_normal: bool = Field(..., description="Whether skin color is normal at this site")
    color_description: Literal["pink", "pale", "mottled", "cyanotic", "flushed"] = Field(
        ..., description="Skin color at this site"
    )

    condition_normal: bool = Field(..., description="Whether skin condition/moisture is normal")
    condition_description: Literal["dry", "moist", "diaphoretic", "clammy"] = Field(
        ..., description="Skin condition/moisture at this site"
    )

    temperature_normal: bool = Field(..., description="Whether skin temperature is normal")
    temperature_description: Literal["warm", "cool", "cold", "hot"] = Field(
        ..., description="Skin temperature at this site"
    )

    __orm_model__ = "trainerlab.PulseAssessment"
