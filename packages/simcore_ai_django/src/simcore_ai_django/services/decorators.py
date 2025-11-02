# packages/simcore_ai_django/src/simcore_ai_django/services/decorators.py
from __future__ import annotations

"""
Django-aware service decorator (class-based, no factories).

This decorator composes the **core** service decorator with the **Django-aware**
base to centralize identity and registration logic:

- Identity is derived via the unified Identity system (resolver-driven).
  The Django resolver infers `namespace` from AppConfig.label → class attr →
  module root, applies Django-specific strip tokens for *derived* names, and
  emits a canonical dot id via `identity.as_str`.
- Sets the **domain default** `kind="service"`.
- Registers the class with the Django services registry; duplicate/collision
  policy is enforced by that registry (see `SIMCORE_COLLISIONS_STRICT`).

No collision rewriting is done here; registries own policy. If you want to
opt-in to dev-only rename-on-collision, override `allow_collision_rewrite()` on
this decorator subclass to return True (recommended OFF in production).
"""

from typing import Any

from simcore_ai.services.decorators import (
    ServiceRegistrationDecorator as CoreServiceDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator
from simcore_ai_django.services.registry import services


# If you have a registry Protocol, import it and use as the return type:
# from simcore_ai_django.services.registry import ServiceRegistry  # hypothetical


class DjangoServiceDecorator(DjangoBaseDecorator, CoreServiceDecorator):
    """Django-aware service decorator.

    Identity derivation is handled by the Django resolver (via the base), and
    registration is performed against the Django services registry.
    """

    # Domain default for kind
    default_kind = "service"

    def get_registry(self) -> Any | None:  # -> ServiceRegistry | None
        """Return the Django services registry singleton."""
        return services


# Ready-to-use decorator instances (short and namespaced aliases)
llm_service = DjangoServiceDecorator()
llm_service.__doc__ = "Decorator for LLM-backed Django services (identity + registry wired)."

ai_service = llm_service
ai_service.__doc__ = "Alias of `llm_service`."

__all__ = ["llm_service", "ai_service", "DjangoServiceDecorator"]
