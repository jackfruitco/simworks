# common/orca/prompts/__init__.py
"""
common prompt components.

Provides shared prompt mixins for SimWorks AI services.
"""

from .mixins import (
    CharacterConsistencyMixin,
    FeedbackEducatorMixin,
    MedicalAccuracyMixin,
    SMSStyleMixin,
)

__all__ = [
    "CharacterConsistencyMixin",
    "FeedbackEducatorMixin",
    "MedicalAccuracyMixin",
    "SMSStyleMixin",
]
