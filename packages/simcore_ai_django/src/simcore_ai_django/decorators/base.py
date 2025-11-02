# packages/simcore_ai_django/src/simcore_ai_django/decorators/base.py
from __future__ import annotations

"""
Django-aware base decorator (class-based, no factories).

Extends the core `BaseDecorator` by wiring in the Django-aware
`DjangoIdentityResolver` as the default identity resolver. This module does **not**
bind to any specific registry; domain decorators (codecs, prompt sections, schemas,
services) should subclass and implement `get_registry()`.

Key properties
--------------
- Identity derivation is delegated to `DjangoIdentityResolver`:
  • namespace: arg → class attr → AppConfig.label → module root → "default"
  • name: segment-aware token stripping (core + Django tokens/settings/env)
- Registration policy is owned by domain registries (collisions, rewrites).
- No Django ORM imports; remains framework-light.

Notes
-----
- Prefer `Identity.as_str` and `Identity.as_tuple3` downstream. This decorator
  does not assume or stamp legacy `identity_str` attributes.
"""

from typing import Any
import logging

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai_django.identity.resolvers import DjangoIdentityResolver

__all__ = ["DjangoBaseDecorator"]

logger = logging.getLogger(__name__)


class DjangoBaseDecorator(BaseDecorator):
    """Django-aware identity pipeline; registration is deferred to domain subclasses."""

    def __init__(self, *, resolver: DjangoIdentityResolver | None = None) -> None:
        # Inject the Django resolver by default; allow override for tests/customization.
        super().__init__(resolver=resolver or DjangoIdentityResolver())

    def get_registry(self) -> Any | None:
        """Return the domain registry singleton (or None).

        Subclasses (e.g., codecs/prompt/schemas/services) must override this to
        provide the appropriate registry object.
        """
        return None

    # --- optional collision policy hook for registries -----------------------
    def allow_collision_rewrite(self) -> bool:
        """Hint for registries when SIMCORE_COLLISIONS_STRICT is false.

        If this returns True, a registry MAY apply a deterministic rename (e.g., `name-2`).
        The base returns False; decisions are left to concrete domain decorators.
        """
        return False
