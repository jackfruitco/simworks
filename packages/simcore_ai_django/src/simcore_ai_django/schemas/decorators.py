# simcore_ai_django/schemas/decorators.py
from __future__ import annotations

"""
Django-aware schema decorator (class-based, no factories).

This decorator composes the core domain decorator with the Django-aware base to:

- derive a finalized Identity `(namespace, kind, name)` using Django-aware
  namespace resolution (AppConfig label → app name → module root) and
  name-only token stripping from AppConfig/global settings,
- set the domain default `kind="schema"`,
- register the class with the Django schemas registry (`schemas`), which
  enforces duplicate vs collision policy controlled by `SIMCORE_COLLISIONS_STRICT`.

No collision rewriting is performed here; registries own policy. If you want to opt-in to dev-only rename-on-collision, override `allow_collision_rewrite()` in a subclass to return True (recommended OFF in production).
"""

from typing import Any

from simcore_ai.schemas.decorators import (
    SchemaRegistrationDecorator as CoreSchemaDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator
from simcore_ai_django.schemas.registry import SchemaRegistry


class DjangoSchemaDecorator(DjangoBaseDecorator, CoreSchemaDecorator):
    """Django-aware schema decorator: identity via DjangoBaseDecorator; registry wired here."""

    # Domain default for kind
    default_kind = "schema"

    def get_registry(self) -> Any | None:
        """Return the Django schemas registry (class with classmethods)."""
        return SchemaRegistry


# Ready-to-use decorator instances (short and namespaced aliases)
schema = DjangoSchemaDecorator()
ai_schema = schema

__all__ = ["schema", "ai_schema", "DjangoSchemaDecorator"]
