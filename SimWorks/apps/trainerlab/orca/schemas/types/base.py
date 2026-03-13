# trainerlab/orca/types/base.py
"""
Base classes for TrainerLab events and vital measurements.

This module defines foundational schema types used for TrainerLab provider outputs.
Vital measurements intentionally exclude transport/debug-only fields from their
provider-facing schema.
"""

from typing import Any, Self

from pydantic import Field, model_validator

from orchestrai_django.types import StrictBaseModel

__all__ = ["BaseEvent", "BaseVitalMeasurement"]


class BaseEvent(StrictBaseModel):
    """Base event schema carrying a kind discriminator."""

    kind: str


class BaseVitalMeasurement(StrictBaseModel):
    """Base schema for vital measurements used by InitialScenarioSchema."""

    min_value: int = Field(..., gt=0)
    max_value: int = Field(..., gt=0)

    lock_value: bool = Field(
        ..., description="Lock the value to the minimum (instead of a range between min and max)"
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_measurement_fields(cls, value: Any) -> Any:
        """Accept and discard legacy keys from older provider responses."""
        if not isinstance(value, dict):
            return value

        cleaned = dict(value)
        for legacy_key in ("db_pk", "timestamp", "kind", "key"):
            cleaned.pop(legacy_key, None)
        return cleaned

    @model_validator(mode="after")
    def validate_min_max_range(self) -> Self:
        if self.min_value > self.max_value:
            raise ValueError("min_value must be less than or equal to max_value")
        return self
