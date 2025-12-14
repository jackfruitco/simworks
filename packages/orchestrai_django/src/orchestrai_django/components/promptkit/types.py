# orchestrai_django/components/promptkit/types.py
from abc import ABC
from typing import ClassVar

from orchestrai.components.promptkit.base import PromptSection, Prompt
from orchestrai.components.promptkit.engine import PromptEngine
from orchestrai.components.promptkit.plans import PromptPlan, PromptSectionSpec

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
