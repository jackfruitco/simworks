# simcore_ai/promptkit/decorators.py
from __future__ import annotations

from typing import Type
from .types import PromptSection
from .registry import PromptRegistry


def prompt(cls: Type[PromptSection]) -> Type[PromptSection]:
    """Register a PromptSection subclass at import time."""
    PromptRegistry.register(cls)
    cls._is_registered_prompt = True  # purely introspection / debugging aid
    return cls

# optional alias for style consistency
register_prompt = prompt