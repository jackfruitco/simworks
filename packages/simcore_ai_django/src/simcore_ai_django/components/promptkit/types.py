from abc import ABC
from typing import ClassVar

from simcore_ai.components.promptkit.base import PromptSection
from simcore_ai.components.promptkit import PromptPlan, PromptSection, Prompt, PromptSectionSpec

__all__ = [
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
