# simcore_ai_django/components/promptkit/types.py
from abc import ABC
from typing import ClassVar

from simcore_ai.components.promptkit.base import PromptSection, Prompt
from simcore_ai.components.promptkit.engine import PromptEngine
from simcore_ai.components.promptkit.plans import PromptPlan, PromptSectionSpec

__all__ = [
    "PromptEngine",
    "PromptScenario",
    "PromptSection",
    "PromptPlan",
    "Prompt",
    "PromptSectionSpec",
]


class PromptScenario(PromptSection, ABC):
    """Prompt scenario

    Not fully implemented yet
    """
    abstract: ClassVar[bool] = True
