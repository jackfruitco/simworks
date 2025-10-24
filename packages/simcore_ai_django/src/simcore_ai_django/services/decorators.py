# packages/simcore_ai_django/src/simcore_ai_django/services/decorators.py
from __future__ import annotations

"""
Django-aware service decorator (class-based, no factories).

This decorator composes the core domain decorator with the Django-aware base to:

- derive a finalized Identity `(namespace, kind, name)` using Django-aware
  namespace resolution (AppConfig label → app name → module root) and
  name-only token stripping from AppConfig/global settings,
- set the domain default `kind="service"`,
- register the class with the Django services registry (`services`), which
  enforces duplicate vs collision policy controlled by `SIMCORE_COLLISIONS_STRICT`.

No collision rewriting is performed here; registries own policy. If you want to
opt-in to dev-only rename-on-collision, override `allow_collision_rewrite()` in
this subclass to return True (recommended OFF in production).
"""

from typing import Any

from simcore_ai.services.decorators import (
    ServiceRegistrationDecorator as CoreServiceDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator
from simcore_ai_django.services.registry import services


class DjangoServiceDecorator(DjangoBaseDecorator, CoreServiceDecorator):
    """Django-aware service decorator: identity via DjangoBaseDecorator; registry wired here."""

    # Domain default for kind
    default_kind = "service"

    def get_registry(self) -> Any | None:
        """Return the Django services registry singleton."""
        return services


# Ready-to-use decorator instances (short and namespaced aliases)
llm_service = DjangoServiceDecorator()
ai_service = llm_service

__all__ = ["llm_service", "ai_service", "DjangoServiceDecorator"]
