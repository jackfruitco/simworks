"""Shared instruction classes for SimWorks services.

All instructions in this app are defined in YAML files (shared.yaml,
feedback.yaml) and registered at Django startup via the OrchestrAI YAML
loader.  Reference them via ``instruction_refs`` using 3-part identity
strings, e.g. ``"common.shared.CharacterConsistencyInstruction"``.
"""

from __future__ import annotations

__all__: list[str] = []
