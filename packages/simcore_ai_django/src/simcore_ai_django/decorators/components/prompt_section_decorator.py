# simcore_ai/decorators/components/prompt_section_decorator.py
"""
Core codec decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "codec" if not provided).
- Registers the class in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

import logging
from typing import Any, Type, TypeVar

from simcore_ai.components.promptkit import PromptSection
from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.registry.base import BaseRegistry
from simcore_ai.registry.singletons import prompt_sections

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class DjangoPromptSectionDecorator(DjangoBaseDecorator):
    """
    Codec decorator specialized for DjangoPromptSectionDecorator subclasses.

    Usage
    -----
        from simcore_ai.decorators import prompt_section

        @prompt_section
        class MyPromptSection(PromptSection):
            ...

        # or with explicit hints
        @prompt_section(namespace="simcore", name="my_section")
        class MyPromptSection(PromptSection):
            ...
    """

    def get_registry(self) -> BaseRegistry:
        return prompt_sections

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register prompt_section classes
        if not issubclass(candidate, PromptSection):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass PromptSection to use @prompt_section"
            )
        super().register(candidate)
