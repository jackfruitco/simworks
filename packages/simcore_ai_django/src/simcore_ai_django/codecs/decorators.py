# simcore_ai_django/codecs/decorators.py
"""Django-aware codec decorator built on the shared base factory.

This module wires the Django-facing `codec` decorator to the core dual-form
class decorator factory using a Django-aware identity resolver. It also
performs collision resolution against the Django codec registry and, in dev
mode, optionally validates that codec classes can be instantiated.

Usage (dual-form):

    from simcore_ai_django.codecs.decorators import codec
    from .base import DjangoBaseLLMCodec

    @codec
    class PatientCodec(DjangoBaseLLMCodec):
        ...

    @codec(origin="chatlab", bucket="sim_responses", name="patient_initial_response")
    class PatientInitialResponseCodec(DjangoBaseLLMCodec):
        ...

Identity rules (Django):
- Uses the leaf concrete class for `name` (mixin-safe), with standardized
  suffix stripping and app/settings-provided tokens.
- `bucket` defaults to "default" when not explicitly provided or derived.
- All parts are normalized to snake_case.

Collisions & registration:
- Before registering, tuple³ collisions are resolved via `resolve_collision_django`.
- Registration stores the **class** in `DjangoCodecRegistry`. Duplicate or
  autoreload re-registrations are tolerated.

Dev-only validation:
- If `settings.SIMCORE_AI_VALIDATE_CODECS_ON_REGISTER` is truthy, the class is
  shallow-instantiated after registration to catch constructor errors early.
  Failures are logged but do not raise at import time.
"""
from __future__ import annotations

import logging
from typing import Type, Any

from django.conf import settings

from simcore_ai.decorators.base import make_class_decorator
from simcore_ai_django.identity import resolve_collision_django
from simcore_ai_django.identity.resolvers import django_identity_resolver
from .registry import DjangoCodecRegistry

logger = logging.getLogger(__name__)


def _post_register_codec(cls: Type[Any]) -> None:
    """Collision-safe registry hook for Django codecs.

    This mutates the class identity if a collision is detected, then registers
    the CLASS with `DjangoCodecRegistry`. In dev mode, optionally attempts a
    shallow instantiation to surface constructor issues early.
    """
    try:
        def _exists(t: tuple[str, str, str]) -> bool:
            try:
                return bool(DjangoCodecRegistry.has(*t))
            except Exception:
                # Fallback to private store if the API is not available
                store = getattr(DjangoCodecRegistry, "_store", None)
                if isinstance(store, dict):
                    return t in store
                return False

        o, b, n = getattr(cls, "origin", ""), getattr(cls, "bucket", ""), getattr(cls, "name", "")
        o, b, n = resolve_collision_django("codec", (o, b, n), exists=_exists)
        setattr(cls, "origin", o)
        setattr(cls, "bucket", b)
        setattr(cls, "name", n)

        try:
            DjangoCodecRegistry.register(o, b, n, cls)
        except Exception as e:
            # Tolerate duplicates (e.g., autoreload) and registry-specific errors
            logger.debug("Codec class registration non-fatal for %s: %s", cls, e)

        # Dev-only shallow constructibility check
        if getattr(settings, "SIMCORE_AI_VALIDATE_CODECS_ON_REGISTER", False):
            try:
                _ = cls()  # noqa: F841
            except Exception as e:  # pragma: no cover - diagnostics only
                logger.warning(
                    "Codec constructibility check failed for %s (%s.%s.%s): %s",
                    cls.__name__, o, b, n, e,
                )
    except Exception as e:
        # Never crash during import. Log at debug for noisy environments.
        logger.debug("Codec post-register hook suppressed an error for %s: %s", cls, e)
        return


# Build the dual-form codec decorator using the shared factory and Django-aware resolver.
codec = make_class_decorator(
    identity_resolver=django_identity_resolver,
    post_register=_post_register_codec,
)

__all__ = ["codec"]
