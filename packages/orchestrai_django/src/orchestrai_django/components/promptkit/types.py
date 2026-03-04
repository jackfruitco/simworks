# orchestrai_django/components/promptkit/types.py
from abc import ABC
from typing import ClassVar

from orchestrai.components.promptkit.base import Prompt, PromptSection
from orchestrai.components.promptkit.engine import PromptEngine
from orchestrai.components.promptkit.plans import PromptPlan, PromptSectionSpec

__all__ = [
    "Prompt",
    "PromptEngine",
    "PromptPlan",
    "PromptScenario",
    "PromptSection",
    "PromptSectionSpec",
]


class PromptScenario(PromptSection, ABC):
    """Prompt scenario

    Not fully implemented yet
    """

    abstract: ClassVar[bool] = True
