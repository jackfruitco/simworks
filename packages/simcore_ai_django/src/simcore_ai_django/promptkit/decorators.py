# simcore_ai_django/promptkit/decorators.py
# simcore_ai_django/promptkit/decorators.py
"""Django-aware decorators for registering PromptSection classes.

Features:
  - Django-aware registration of PromptSection and related types.
  - Auto-derivation of (origin, bucket, name) identity using Django app label and shared rules.
  - Canonical dot-only identity strings for prompt registration.
"""

from __future__ import annotations

import logging
from typing import Type

from simcore_ai.promptkit.registry import PromptRegistry
from simcore_ai.promptkit.types import PromptSection
from simcore_ai_django.identity import derive_django_identity_for_class

logger = logging.getLogger(__name__)


def _ensure_identity(cls: Type[PromptSection]) -> None:
    """Ensure a PromptSection class has (origin, bucket, name) set using Django-aware derivation."""
    has_parts = all(isinstance(getattr(cls, k, None), str) and getattr(cls, k) for k in ("origin", "bucket", "name"))
    if has_parts:
        return
    org, buck, nm = derive_django_identity_for_class(
        cls,
        origin=getattr(cls, "origin", None),
        bucket=getattr(cls, "bucket", None),
        name=getattr(cls, "name", None),
    )
    setattr(cls, "origin", org)
    setattr(cls, "bucket", buck)
    setattr(cls, "name", nm)
    logger.info("Prompt identity derived for %s -> %s.%s.%s", cls.__name__, org, buck, nm)


def _register_prompt_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    _ensure_identity(cls)
    PromptRegistry.register(cls)
    setattr(cls, "_is_registered_prompt", True)
    return cls


# Public decorators (Django-aware, identity defaults)
def prompt_section(cls: Type[PromptSection]) -> Type[PromptSection]:
    """Django-aware decorator that registers a PromptSection and auto-fills identity.

    If (origin, bucket, name) are not declared on the class, we will:
      - set `origin` to the Django app label for the class' module
      - set `bucket` to `"default"`
      - derive `name` from the class name with common suffixes removed
    """
    return _register_prompt_section(cls)


# If you add scenarios later, they can reuse the same identity rules
prompt_scenario = prompt_section
