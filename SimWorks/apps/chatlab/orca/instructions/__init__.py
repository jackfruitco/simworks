"""Instruction classes for chatlab services.

Dynamic instructions are defined here and imported directly.
Static instructions are defined in YAML files in this directory and are registered
at Django startup via the OrchestrAI YAML loader. This module provides
backward-compatible access to those static classes via ``__getattr__``.
"""

from __future__ import annotations

from .lab_orders import LabOrderPatientContextInstruction, LabOrderTestListInstruction
from .patient import PatientNameInstruction, PatientRecentScenarioHistoryInstruction
from .stitch import StitchConversationContextInstruction, StitchPersonaInstruction

# Backward-compat aliases for dynamic classes (same object, different name)
# These remain importable by their old alias names.
_ALIASES: dict[str, str] = {}

# All names exported by this module (dynamic + YAML-generated).
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

# Aliases: legacy name → canonical YAML class name.
_YAML_ALIASES: dict[str, str] = {
    "PatientBaseInstruction": "PatientConversationBehaviorInstruction",
    "PatientScenarioInstruction": "PatientConversationBehaviorInstruction",
    "PatientStyleInstruction": "PatientConversationBehaviorInstruction",
    "PatientFieldSemanticsInstruction": "PatientSchemaContractInstruction",
    "StitchReplyDetailInstruction": "StitchDebriefInstruction",
    "StitchStyleInstruction": "StitchToneInstruction",
    "StitchFieldSemanticsInstruction": "StitchSchemaContractInstruction",
}


def __getattr__(name: str):
    """Lazy registry lookup for YAML-generated (static) instruction classes."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    canonical = _YAML_ALIASES.get(name, name)
    try:
        from orchestrai._state import get_current_app
        from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

        app = get_current_app()
        cls = app.components.registry(INSTRUCTIONS_DOMAIN).find_by_name(canonical)
        if cls is not None:
            return cls
    except Exception:
        pass
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}. "
        "Ensure OrchestrAI has been started (Django app ready) before importing."
    )
