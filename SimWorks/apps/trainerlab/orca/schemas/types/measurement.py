# trainerlab/orca/types/measurement.py
"""
Defines the vital measurement types for various health metrics used in medical analysis.

This module provides class representations for different types of vital measurements,
extending the functionality of the `BaseVitalMeasurement` class. Each subclass represents
a specific type of vital measurement that might be used for tracking or analysis in
healthcare applications or systems. The included classes represent metrics such as heart
rate, blood oxygen saturation (SpO2), carbon dioxide levels (ETCO2), blood glucose levels,
and blood pressures.

Classes:
    - HeartRate: Represents a measurement of heart rate.
    - SPO2: Represents blood oxygen saturation levels.
    - ETCO2: Represents end-tidal carbon dioxide levels.
    - BloodGlucoseLevel: Represents a measurement of blood glucose level.
    - BloodPressure: Represents a measurement of blood pressure, including systolic
      and diastolic ranges.
"""

from typing import Self

from pydantic import Field, model_validator

from .base import BaseVitalMeasurement

__all__ = ["ETCO2", "SPO2", "BloodGlucoseLevel", "BloodPressure", "HeartRate"]


class HeartRate(BaseVitalMeasurement):
    """OpenAI-compatible Pydantic model for a HeartRate measurement range."""

    __orm_model__ = "trainerlab.HeartRate"


class SPO2(BaseVitalMeasurement):
    """OpenAI-compatible Pydantic model for a SPO2 measurement range."""

    __orm_model__ = "trainerlab.SPO2"


class ETCO2(BaseVitalMeasurement):
    """OpenAI-compatible Pydantic model for a ETCO2 measurement range."""

    __orm_model__ = "trainerlab.ETCO2"


class BloodGlucoseLevel(BaseVitalMeasurement):
    """OpenAI-compatible Pydantic model for a BloodGlucoseLevel measurement range."""

    __orm_model__ = "trainerlab.BloodGlucoseLevel"


class BloodPressure(BaseVitalMeasurement):
    """OpenAI-compatible Pydantic model for a BloodPressure measurement range.

    `min_value` and `max_value` are used for systolic pressures
    """

    min_value_diastolic: int = Field(
        ..., gt=0, lt=150, description="Minimum diastolic blood pressure"
    )
    max_value_diastolic: int = Field(
        ..., gt=0, lt=150, description="Maximum diastolic blood pressure"
    )

    __orm_model__ = "trainerlab.BloodPressure"

    @model_validator(mode="after")
    def validate_blood_pressure_ranges(self) -> Self:
        if self.min_value_diastolic > self.max_value_diastolic:
            raise ValueError(
                "min_value_diastolic must be less than or equal to max_value_diastolic"
            )
        if self.min_value < self.min_value_diastolic:
            raise ValueError("Systolic min_value must be greater than or equal to diastolic min")
        if self.max_value < self.max_value_diastolic:
            raise ValueError("Systolic max_value must be greater than or equal to diastolic max")
        return self
