# simcore_ai_django/promptkit/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from .decorators import prompt_section, prompt_scenario
from .types import PromptSection, PromptScenario

if TYPE_CHECKING:
    from simcore_ai.promptkit import Prompt, PromptEngine, PromptRegistry

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
    """Lazily import simcore_ai.promptkit symbols to avoid circular import."""
    if name in {"Prompt", "PromptEngine", "PromptRegistry"}:
        from simcore_ai import promptkit as _core_promptkit
        return getattr(_core_promptkit, name)
    raise AttributeError(name)