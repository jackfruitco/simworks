"""Instruction classes for chatlab services."""

from __future__ import annotations

from .image import ImageGenerationInstruction
from .lab_orders import (
    LabOrderPatientContextInstruction,
    LabOrderResultDetailInstruction,
    LabOrderSchemaContractInstruction,
    LabOrderTestListInstruction,
)
from .patient import (
    PatientConversationBehaviorInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientRecentScenarioHistoryInstruction,
    PatientReplyDetailInstruction,
    PatientSafetyBoundariesInstruction,
    PatientSchemaContractInstruction,
)
from .stitch import (
    StitchConversationContextInstruction,
    StitchDebriefInstruction,
    StitchPersonaInstruction,
    StitchRoleInstruction,
    StitchSchemaContractInstruction,
    StitchToneInstruction,
)

# Backwards-compatible alias used by older tests/callers.
PatientBaseInstruction = PatientConversationBehaviorInstruction
StitchReplyDetailInstruction = StitchDebriefInstruction

__all__ = [
    "ImageGenerationInstruction",
    "LabOrderPatientContextInstruction",
    "LabOrderResultDetailInstruction",
    "LabOrderSchemaContractInstruction",
    "LabOrderTestListInstruction",
    "PatientBaseInstruction",
    "PatientConversationBehaviorInstruction",
    "PatientInitialDetailInstruction",
    "PatientNameInstruction",
    "PatientRecentScenarioHistoryInstruction",
    "PatientReplyDetailInstruction",
    "PatientSafetyBoundariesInstruction",
    "PatientSchemaContractInstruction",
    "StitchConversationContextInstruction",
    "StitchDebriefInstruction",
    "StitchPersonaInstruction",
    "StitchReplyDetailInstruction",
    "StitchRoleInstruction",
    "StitchSchemaContractInstruction",
    "StitchToneInstruction",
]
