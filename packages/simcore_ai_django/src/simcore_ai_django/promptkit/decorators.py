# simcore_ai_django/promptkit/decorators.py
"""Django-aware PromptKit decorators built on the shared base factory.

This module wires Django-facing prompt decorators to the core dual-form
factory using a Django-aware identity resolver. It keeps imports one-way
(Django ➜ core) and avoids registry or identity logic duplication.

Exports:
- `prompt_section`: dual-form decorator for `PromptSection` subclasses.
- `prompt_scenario`: (stub) future decorator for scenario-level prompts.

Identity rules (Django):
- Uses the **leaf concrete class** for `name` (mixin-safe), with standardized
  suffix stripping and app/settings-provided tokens.
- `bucket` defaults to "default" when not explicitly provided or derived.
- All parts are normalized to snake_case.

Collisions:
- Prompt section collisions are handled by the PromptRegistry implementation
  (which may apply renames). Collision policy is intentionally *not* embedded
  in the resolver to keep it pure and composable.
"""
from __future__ import annotations

import warnings
from typing import Optional, Type, Callable, Any, overload

from simcore_ai.decorators.base import make_class_decorator
from simcore_ai.promptkit import PromptRegistry, PromptSection
from simcore_ai_django.identity.resolvers import django_identity_resolver

# Build the dual-form decorator using the shared factory and Django-aware resolver.
prompt_section = make_class_decorator(
    identity_resolver=django_identity_resolver,
    post_register=PromptRegistry.register,
)


@overload
def prompt_scenario(
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Callable[[Type[PromptSection]], Type[PromptSection]]: ...


@overload
def prompt_scenario(
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Callable[[Type[PromptSection]], Type[PromptSection]]: ...


def prompt_scenario(
        cls: Optional[Type[PromptSection]] = None,
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Any:
    """Stub for a future scenario-level prompt decorator.

    This will likely validate additional scenario metadata and register the
    class with a ScenarioRegistry. For now, it only warns and returns the
    class unchanged to avoid breaking imports.
    """
    warnings.warn("`prompt_scenario` decorator is not yet implemented")
    return cls


__all__ = ["prompt_section", "prompt_scenario", "PromptSection"]
