# packages/orchestrai_django/src/orchestrai_django/decorators/base.py
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
"""


import logging
from typing import Any

from orchestrai.decorators.base import BaseDecorator
from orchestrai.identity import IdentityResolverProtocol
from orchestrai_django.identity.resolvers import DjangoIdentityResolver

__all__ = ["DjangoBaseDecorator"]

logger = logging.getLogger(__name__)


class DjangoBaseDecorator(BaseDecorator):
    """Thin Django-aware decorator.

    - Delegates identity derivation/pinning to core BaseDecorator
    - Resolves registries using the Django integration registries
    - Avoids importing core registries directly
    """

    def __init__(self, *, resolver: IdentityResolverProtocol | None = None) -> None:
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
        from orchestrai_django.settings import STRICT_COLLISIONS
        return STRICT_COLLISIONS or False
