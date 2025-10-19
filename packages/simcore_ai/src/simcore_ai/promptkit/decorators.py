# simcore_ai/promptkit/decorators.py
"""Core (non-Django) decorators for PromptKit that auto-derive tuple3 identities using core rules."""

from __future__ import annotations

import logging
from typing import Type

from simcore_ai.identity import derive_identity_for_class
from . import PromptScenario
from .registry import PromptRegistry
from .types import PromptSection

logger = logging.getLogger(__name__)


def prompt_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    """Decorator to register a `PromptSection` subclass in the global registry (AIv3).

    The class must declare tuple3 identity `(origin, bucket, name)` in dot-only canonical form,
    or the decorator will auto-derive missing parts using module-root origin, default bucket,
    and stripped/snake-cased class name.

    Example:
        >>> @prompt_section
        ... class PatientIntro(PromptSection):
        ...     origin = "chatlab"
        ...     bucket = "patient"
        ...     name = "intro"
        ...     instruction = "Gather patient demographics."
    """
    has_parts = all(isinstance(getattr(cls, k, None), str) and getattr(cls, k) for k in ("origin", "bucket", "name"))
    if not has_parts:
        org, buck, nm = derive_identity_for_class(
            cls,
            origin=getattr(cls, "origin", None),
            bucket=getattr(cls, "bucket", None),
            name=getattr(cls, "name", None),
        )
        setattr(cls, "origin", org)
        setattr(cls, "bucket", buck)
        setattr(cls, "name", nm)
    try:
        PromptRegistry.register(cls)
        cls._is_registered_prompt = True  # introspection / debugging aid
        logger.debug("Registered prompt section: %s",
                     f"{getattr(cls, 'origin', '?')}.{getattr(cls, 'bucket', '?')}.{getattr(cls, 'name', '?')}")
    except Exception as e:
        logger.exception("Failed to register prompt section %s: %s", cls, e)
        raise
    return cls


def prompt_scenario(cls: Type[PromptScenario]) -> Type[PromptScenario]:
    """Decorator to register a `PromptScenario` subclass in the global registry (AIv3).

    The class must declare tuple3 identity `(origin, bucket, name)` in dot-only canonical form,
    or the decorator will auto-derive missing parts using module-root origin, default bucket,
    and stripped/snake-cased class name.

    Example:
        >>> @prompt_scenario
        ... class StrepThroatScenario(PromptScenario):
        ...     origin = "chatlab"
        ...     bucket = "patient"
        ...     name = "intro"
        ...     instruction = "Gather patient demographics."
    """
    has_parts = all(isinstance(getattr(cls, k, None), str) and getattr(cls, k) for k in ("origin", "bucket", "name"))
    if not has_parts:
        org, buck, nm = derive_identity_for_class(
            cls,
            origin=getattr(cls, "origin", None),
            bucket=getattr(cls, "bucket", None),
            name=getattr(cls, "name", None),
        )
        setattr(cls, "origin", org)
        setattr(cls, "bucket", buck)
        setattr(cls, "name", nm)
    try:
        PromptRegistry.register(cls)
        cls._is_registered_prompt = True  # introspection / debugging aid
        logger.debug("Registered prompt scenario: %s",
                     f"{getattr(cls, 'origin', '?')}.{getattr(cls, 'bucket', '?')}.{getattr(cls, 'name', '?')}")
    except Exception as e:
        logger.exception("Failed to register prompt scenario %s: %s", cls, e)
        raise
    return cls
