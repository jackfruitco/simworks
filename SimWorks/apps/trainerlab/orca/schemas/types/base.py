# trainerlab/orca/types/base.py
"""
Base classes for TrainerLab events and vital measurements.

This module defines the foundational classes for handling events and vital
measurements in TrainerLab. These classes are designed to provide essential
data structures for event and measurement handling while leveraging the
validation capabilities of Pydantic.

Classes:
    BaseEvent: Defines the schema for events, including essential attributes
    like kind, key, and timestamp.

    BaseVitalMeasurement: Extends BaseEvent and includes additional attributes
    for vital measurements, such as min_value, max_value, and lock_value.
"""

from typing import Annotated, Self

from pydantic import Field, model_validator

from orchestrai_django.types import StrictBaseModel

__all__ = ["BaseEvent", "BaseVitalMeasurement"]


class BaseEvent(StrictBaseModel):
    """Base event schema for the TrainerLab Events."""

    kind: str
    key: str = Field(..., max_length=255)
    timestamp: Annotated[int, Field(ge=0)] = Field(...)

    db_pk: int | None = None


class BaseVitalMeasurement(BaseEvent):
    min_value: int = Field(..., gt=0)
    max_value: int = Field(..., gt=0)

    lock_value: bool = Field(
        ..., description="Lock the value to the minimum (instead of a range between min and max)"
    )

    @model_validator(mode="after")
    def validate_min_max_range(self) -> Self:
        if self.min_value > self.max_value:
            raise ValueError("min_value must be less than or equal to max_value")
        return self
