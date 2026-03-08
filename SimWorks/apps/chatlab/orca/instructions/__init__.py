"""Instruction classes for chatlab services."""

from .image import ImageGenerationInstruction
from .patient import (
    PatientBaseInstruction,
    PatientConversationBehaviorInstruction,
    PatientFieldSemanticsInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientReplyDetailInstruction,
    PatientSafetyBoundariesInstruction,
    PatientScenarioInstruction,
    PatientSchemaContractInstruction,
    PatientStyleInstruction,
)
from .stitch import (
    StitchConversationContextInstruction,
    StitchDebriefInstruction,
    StitchFieldSemanticsInstruction,
    StitchPersonaInstruction,
    StitchReplyDetailInstruction,
    StitchRoleInstruction,
    StitchSchemaContractInstruction,
    StitchStyleInstruction,
    StitchToneInstruction,
)

__all__ = [
    "ImageGenerationInstruction",
    "PatientBaseInstruction",
    "PatientConversationBehaviorInstruction",
    "PatientFieldSemanticsInstruction",
    "PatientInitialDetailInstruction",
    "PatientNameInstruction",
    "PatientReplyDetailInstruction",
    "PatientSafetyBoundariesInstruction",
    "PatientScenarioInstruction",
    "PatientSchemaContractInstruction",
    "PatientStyleInstruction",
    "StitchConversationContextInstruction",
    "StitchDebriefInstruction",
    "StitchFieldSemanticsInstruction",
    "StitchPersonaInstruction",
    "StitchReplyDetailInstruction",
    "StitchRoleInstruction",
    "StitchSchemaContractInstruction",
    "StitchStyleInstruction",
    "StitchToneInstruction",
]
