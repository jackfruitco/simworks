"""Instruction classes for chatlab services."""

from .image import ImageGenerationInstruction
from .lab_orders import (
    LabOrderPatientContextInstruction,
    LabOrderResultDetailInstruction,
    LabOrderSchemaContractInstruction,
    LabOrderTestListInstruction,
)
from .patient import (
    PatientBaseInstruction,
    PatientConversationBehaviorInstruction,
    PatientFieldSemanticsInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientRecentScenarioHistoryInstruction,
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
    "LabOrderPatientContextInstruction",
    "LabOrderResultDetailInstruction",
    "LabOrderSchemaContractInstruction",
    "LabOrderTestListInstruction",
    "PatientBaseInstruction",
    "PatientConversationBehaviorInstruction",
    "PatientFieldSemanticsInstruction",
    "PatientInitialDetailInstruction",
    "PatientNameInstruction",
    "PatientRecentScenarioHistoryInstruction",
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
