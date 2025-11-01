# simcore_ai_django/promptkit/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from .decorators import prompt_section, prompt_scenario
from .types import PromptScenario

# IMPORTANT:
# To enforce the SimWorks import boundary (SimWorks -> simcore_ai_django only)
# AND to guarantee a single canonical Prompt* type across core and facade,
# we lazily re-export ALL core promptkit symbols directly from simcore_ai.promptkit.
# This avoids accidental shadow classes living under simcore_ai_django.promptkit.types.

if TYPE_CHECKING:
    # During type checking, resolve from core to keep a single symbol identity.
    from simcore_ai.promptkit import (
        Prompt,
        PromptEngine,
        PromptRegistry,
        PromptSection,
    )

__all__ = [
    "Prompt",
    "PromptSection",
    "PromptScenario",
    "PromptEngine",
    "PromptRegistry",
    "prompt_section",
    "prompt_scenario",
]


def __getattr__(name: str):
    """Lazily import simcore_ai.promptkit symbols to avoid circular import.

    We intentionally re-export PromptSection/PromptScenario from core to ensure
    isinstance/issubclass checks inside the core PromptEngine work with the
    exact same class objects (no facade shadow classes).
    """
    if name in {
        "Prompt",
        "PromptEngine",
        "PromptRegistry",
        "PromptSection",
    }:
        from simcore_ai import promptkit as _core_promptkit
        return getattr(_core_promptkit, name)
    raise AttributeError(name)