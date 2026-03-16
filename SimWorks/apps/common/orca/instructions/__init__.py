"""Shared instruction mixins for SimWorks services.

Static instructions are defined in YAML files (shared.yaml, feedback.yaml) in this
directory and are registered at Django startup via the OrchestrAI YAML loader.
This module provides backward-compatible access to those classes via ``__getattr__``.
"""

from __future__ import annotations

__all__ = [
    "CharacterConsistencyInstruction",
    "FeedbackEducatorInstruction",
    "MedicalAccuracyInstruction",
    "SMSStyleInstruction",
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
