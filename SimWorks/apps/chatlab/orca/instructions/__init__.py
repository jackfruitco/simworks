"""Instruction classes for chatlab services."""

from __future__ import annotations

from .image import ImageGenerationInstruction
from .lab_orders import (
    LabOrderPatientContextInstruction,
    LabOrderResultDetailInstruction,
    LabOrderSchemaContractInstruction,
    LabOrderTestListInstruction,
)
from .patient import PatientNameInstruction, PatientRecentScenarioHistoryInstruction
from .stitch import (
    StitchConversationContextInstruction,
    StitchDebriefInstruction,
    StitchPersonaInstruction,
    StitchRoleInstruction,
    StitchSchemaContractInstruction,
    StitchToneInstruction,
)

StitchReplyDetailInstruction = StitchDebriefInstruction

__all__ = [
    "ImageGenerationInstruction",
    "LabOrderPatientContextInstruction",
    "LabOrderResultDetailInstruction",
    "LabOrderSchemaContractInstruction",
    "LabOrderTestListInstruction",
    "PatientNameInstruction",
    "PatientRecentScenarioHistoryInstruction",
    "StitchConversationContextInstruction",
    "StitchDebriefInstruction",
    "StitchPersonaInstruction",
    "StitchReplyDetailInstruction",
    "StitchRoleInstruction",
    "StitchSchemaContractInstruction",
    "StitchToneInstruction",
]
