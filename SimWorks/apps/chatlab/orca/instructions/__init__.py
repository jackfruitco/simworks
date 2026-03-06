"""Instruction classes for chatlab services."""

from .image import ImageGenerationInstruction
from .patient import (
    PatientBaseInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientReplyContextInstruction,
    PatientReplyDetailInstruction,
)
from .stitch import (
    StitchConversationContextInstruction,
    StitchPersonaInstruction,
    StitchReplyDetailInstruction,
)

__all__ = [
    "ImageGenerationInstruction",
    "PatientBaseInstruction",
    "PatientInitialDetailInstruction",
    "PatientNameInstruction",
    "PatientReplyContextInstruction",
    "PatientReplyDetailInstruction",
    "StitchConversationContextInstruction",
    "StitchPersonaInstruction",
    "StitchReplyDetailInstruction",
]
