# orchestrai/decorators/components/prompt_section_decorator.py
"""
Core codec decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "codec" if not provided).
- Registers the class in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

import logging
from typing import Any, Type, TypeVar

from orchestrai.components.promptkit import PromptSection
from orchestrai.decorators.base import BaseDecorator
from orchestrai.registry.base import ComponentRegistry
from orchestrai.registry.singletons import prompt_sections as _Registry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class PromptSectionDecorator(BaseDecorator):
    """
    Codec decorator specialized for DjangoPromptSectionDecorator subclasses.

    Usage
    -----
        from orchestrai.decorators import prompt_section

        @prompt_section
        class MyPromptSection(PromptSection):
            ...

        # or with explicit hints
        @prompt_section(namespace="simcore", name="my_section")
        class MyPromptSection(PromptSection):
            ...
    """

    def get_registry(self) -> ComponentRegistry:
        return _Registry

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register prompt_section classes
        if not issubclass(candidate, PromptSection):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass PromptSection to use @prompt_section"
            )
        super().register(candidate)
