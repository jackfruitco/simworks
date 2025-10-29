# packages/simcore_ai_django/src/simcore_ai_django/decorators/base.py
from __future__ import annotations

"""
Django-aware base decorator (class-based, no factories).

This class extends the core `BaseDecorator` by wiring in the Django-aware
`DjangoIdentityResolver` as the default resolver. It **does not** implement
registration policy; domain-specific Django decorators override `get_registry()`
to return the appropriate registry singleton.

Key points:
- Identity derivation is delegated to `DjangoIdentityResolver` (namespace from
  app label; segment-aware token stripping including app/settings/env tokens).
- Single post-registration trace span is emitted by `BaseDecorator` using the
  resolver-provided `meta` attributes (and filtered by SIMCORE_TRACE_LEVEL).
- Collision handling remains the responsibility of the domain registries.

IMPORTANT:
- No ORM or model imports; this module must remain framework-light.
"""

from typing import Any
import logging

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai_django.identity.resolution import DjangoIdentityResolver

logger = logging.getLogger(__name__)


class DjangoBaseDecorator(BaseDecorator):
    """Django-aware identity pipeline; registration deferred to domain subclasses."""

    def __init__(self, *, resolver: DjangoIdentityResolver | None = None) -> None:
        # Inject the Django resolver by default; allow override for tests/customization
        super().__init__(resolver=resolver or DjangoIdentityResolver())

    def get_registry(self) -> Any | None:  # domain subclasses override to bind a registry
        return None

    # --- optional collision policy hook for registries -----------------------
    def allow_collision_rewrite(self) -> bool:
        """Hint for registries when SIMCORE_COLLISIONS_STRICT is false.

        If this returns True, a registry MAY apply a deterministic rename (e.g.,
        `name-2`). The base returns False; leave decisions to concrete domains.
        """
        return False
