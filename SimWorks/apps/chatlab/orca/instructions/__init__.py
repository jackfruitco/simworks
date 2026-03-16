"""Instruction classes for chatlab services.

Dynamic (Python-defined) instructions are imported directly below.
Static instructions are defined in YAML files in this directory and are
registered at Django startup via the OrchestrAI YAML loader; reference them
via ``instruction_refs`` using 3-part identity strings, e.g.
``"chatlab.patient.PatientSafetyBoundariesInstruction"``.
"""

from __future__ import annotations

from .lab_orders import LabOrderPatientContextInstruction, LabOrderTestListInstruction
from .patient import PatientNameInstruction, PatientRecentScenarioHistoryInstruction
from .stitch import StitchConversationContextInstruction, StitchPersonaInstruction

__all__ = [
    "LabOrderPatientContextInstruction",
    "LabOrderTestListInstruction",
    "PatientNameInstruction",
    "PatientRecentScenarioHistoryInstruction",
    "StitchConversationContextInstruction",
    "StitchPersonaInstruction",
]
