# orchestrai/decorators/components/prompt_section_decorator.py
"""
Core prompt section decorator.

- Derives & pins identity via IdentityResolver (domain/namespace/group/name via resolver + hints).
- Registers the class in the global `prompt_sections` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

import logging
from typing import Any, Type

from orchestrai.components.promptkit import PromptSection
from orchestrai.decorators.base import BaseDecorator
from orchestrai.identity.domains import PROMPT_SECTIONS_DOMAIN
from orchestrai.registry import prompt_sections as _Registry
from orchestrai.registry.base import ComponentRegistry

logger = logging.getLogger(__name__)

__all__ = ("PromptSectionDecorator",)


class PromptSectionDecorator(BaseDecorator):
    """
    Prompt section decorator specialized for PromptSection subclasses.

    Usage
    -----
        from orchestrai.decorators import prompt_section

        @prompt_section
        class MyPromptSection(PromptSection):
            ...

        # or with explicit hints
        @prompt_section(namespace="simcore", group="sections", name="my_section")
        class MyPromptSection(PromptSection):
            ...
    """

    default_domain = PROMPT_SECTIONS_DOMAIN

    def get_registry(self) -> ComponentRegistry:
        return _Registry

    # Human-friendly log label
    log_category = "prompt_sections"

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register prompt_section classes
        if not issubclass(candidate, PromptSection):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass PromptSection to use @prompt_section"
            )
        super().register(candidate)
