"""Instruction classes for simcore services.

All instructions in this app are defined in YAML files and registered at
Django startup via the OrchestrAI YAML loader.  Reference them via
``instruction_refs`` using 3-part identity strings, e.g.
``"simcore.stitch.BaseStitchPersona"``.
"""

from __future__ import annotations

__all__: list[str] = []
