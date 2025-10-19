# simcore_ai/promptkit/decorators.py
from __future__ import annotations

from typing import Type
import logging

from . import PromptScenario
from .types import PromptSection
from .registry import PromptRegistry


logger = logging.getLogger(__name__)


def prompt_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    """Decorator to register a `PromptSection` subclass in the global registry (AIv3).

    The class must declare either:
        • `identity: Identity`
        • or class attrs `origin`, `bucket`, and `name` (strings)

    Example:
        >>> @prompt_section
        ... class PatientIntro(PromptSection):
        ...     origin = "chatlab"
        ...     bucket = "patient"
        ...     name = "intro"
        ...     instruction = "Gather patient demographics."
    """
    try:
        PromptRegistry.register(cls)
        cls._is_registered_prompt = True  # introspection / debugging aid
        logger.debug("Registered prompt section: %s", getattr(cls, 'identity', None) or cls.__name__)
    except Exception as e:
        logger.exception("Failed to register prompt section %s: %s", cls, e)
        raise
    return cls

def prompt_scenario(cls: Type[PromptScenario]) -> Type[PromptScenario]:
    """Decorator to register a `PromptSection` subclass in the global registry (AIv3).

    The class must declare either:
        • `identity: Identity`
        • or class attrs `origin`, `bucket`, and `name` (strings)

    Example:
        >>> @prompt_scenario
        ... class StrepThroatScenario(PromptScenario):
        ...     origin = "chatlab"
        ...     bucket = "patient"
        ...     name = "intro"
        ...     instruction = "Gather patient demographics."
    """
    try:
        PromptRegistry.register(cls)
        cls._is_registered_prompt = True  # introspection / debugging aid
        logger.debug("Registered prompt scenario: %s", getattr(cls, 'identity', None) or cls.__name__)
    except Exception as e:
        logger.exception("Failed to register prompt scenario %s: %s", cls, e)
        raise
    return cls