# common/orca/prompts/__init__.py
"""
common prompt components.

Provides shared prompt mixins for SimWorks AI services.
"""

from .mixins import (
    CharacterConsistencyMixin,
    MedicalAccuracyMixin,
    SMSStyleMixin,
    FeedbackEducatorMixin,
)

__all__ = [
    "CharacterConsistencyMixin",
    "MedicalAccuracyMixin",
    "SMSStyleMixin",
    "FeedbackEducatorMixin",
]
