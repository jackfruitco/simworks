from __future__ import annotations

from typing import Type
from .types import PromptSection
from .registry import PromptRegistry


def register_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    """
    Class decorator to register a PromptSection subclass on definition.
    Usage:

        @register_section
        class BaseSection(PromptSection):
            category = "lab"
            name = "ChatLab"
            weight = 10
            content = "..."

    TODO rename to `register_prompt` or `register_prompt_section`
    """
    PromptRegistry.register(cls)
    return cls