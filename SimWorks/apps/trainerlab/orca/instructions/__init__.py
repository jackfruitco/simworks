"""Instruction classes for TrainerLab services.

Dynamic instructions are defined in Python modules in this directory.
Static instructions are defined in YAML files and registered at Django startup.
This module provides backward-compatible access to both.
"""

from __future__ import annotations

from .debrief import TrainerDebriefContextInstruction
from .initial import InjuryCodebookMixin
from .runtime import TrainerRuntimeContextInstruction

__all__ = [
    "CombatMixin",
    "InitialResponseMixin",
    "InjuryCodebookMixin",
    "MedicalMixin",
    "MilitaryMedicMixin",
    "SpecOpsMedicMixin",
    "TrainerDebriefContextInstruction",
    "TrainerDebriefContractInstruction",
    "TrainerDebriefRoleInstruction",
    "TrainerLabMixin",
    "TrainerRuntimeContextInstruction",
    "TrainerRuntimeContractInstruction",
    "TrainerRuntimeRoleInstruction",
    "TraumaMixin",
]


def __getattr__(name: str):
    """Lazy registry lookup for YAML-generated instruction classes."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        from orchestrai._state import get_current_app
        from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

        app = get_current_app()
        cls = app.components.registry(INSTRUCTIONS_DOMAIN).find_by_name(name)
        if cls is not None:
            return cls
    except Exception:
        pass
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}. "
        "Ensure OrchestrAI has been started (Django app ready) before importing."
    )
