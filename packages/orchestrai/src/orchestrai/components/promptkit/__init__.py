"""
OrchestrAI PromptKit Module (DEPRECATED).

.. deprecated:: 0.5.0
    This module is deprecated and will be removed in OrchestrAI 1.0.
    Use @system_prompt decorators on service methods instead.

Migration Guide:
    Before (using PromptSection):
        @prompt_section
        @dataclass
        class MySection(PromptSection):
            instruction = "..."

        class MyService(BaseService):
            prompt_plan = ("my_section",)

    After (using @system_prompt):
        from orchestrai.prompts import system_prompt

        class MyService(PydanticAIService):
            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "..."
"""
import warnings

warnings.warn(
    "orchestrai.components.promptkit is deprecated and will be removed in OrchestrAI 1.0. "
    "Use @system_prompt decorators on service methods instead. "
    "See orchestrai.prompts for the new API.",
    DeprecationWarning,
    stacklevel=2,
)

from .base import Prompt, PromptSection
from .engine import PromptEngine
from .plans import PromptPlan, PromptSectionSpec

__all__ = [
    "Prompt",
    "PromptSection",
    "PromptEngine",
    "PromptPlan",
    "PromptSectionSpec",
]