"""Instruction classes for TrainerLab services.

Dynamic (Python-defined) instructions are imported directly below.
Static instructions are defined in YAML files in this directory and are
registered at Django startup via the OrchestrAI YAML loader; reference them
via ``instruction_refs`` using 3-part identity strings, e.g.
``"trainerlab.initial.TrainerLabMixin"``.
"""

from __future__ import annotations

from .debrief import TrainerDebriefContextInstruction
from .initial import InjuryCodebookMixin
from .runtime import TrainerRuntimeContextInstruction

__all__ = [
    "InjuryCodebookMixin",
    "TrainerDebriefContextInstruction",
    "TrainerRuntimeContextInstruction",
]
