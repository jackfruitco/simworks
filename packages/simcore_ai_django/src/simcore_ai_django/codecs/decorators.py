# simcore_ai_django/codecs/decorators.py
"""Django-aware codec decorator.

This module provides a drop-in `@codec` decorator for Django projects that:

- Works with **classes only** (codecs must be class types). Function targets
  are rejected by the core decorator.
- Resolves identity with **Django-aware defaults** (AppConfig-aware) and merges
  additional strip tokens from env/settings/app contributions (via mixins).
- Registers codecs using the **Django** registry
  (`simcore_ai_django.codecs.registry.DjangoCodecRegistry`) and enforces
  tuple³ uniqueness. On duplicate, the decorator appends a hyphen-int suffix
  to the **name** (`name-2`, `-3`, …) and retries, logging a WARNING each time.
- Never crashes at import-time.

Composition:
    DjangoCodecRegistrationMixin.register()  -> forces Django registry usage
    DjangoSimcoreIdentityMixin               -> identity & token behavior
    _CoreCodecDecorator                      -> core class-only & base logic
"""
from __future__ import annotations

import logging

from simcore_ai.codecs.decorators import CodecDecorator as _CoreCodecDecorator
from simcore_ai_django.decorators.mixins import DjangoSimcoreIdentityMixin

log = logging.getLogger(__name__)


class DjangoCodecRegistrationMixin:
    """Override `register` to use the Django codec registry with collision suffixing."""

    def register(self, obj):  # type: ignore[override]
        """
        Register the codec class using the **Django** registry, enforcing tuple³ uniqueness
        and handling collisions by suffixing the *name* (`name-2`, `-3`, ...).
        """
        # Lazy import to avoid hard dependency at import-time
        try:
            from simcore_ai_django.codecs.registry import (
                DjangoCodecRegistry as Registry,
                DuplicateCodecIdentityError,
            )
        except Exception:  # pragma: no cover
            log.debug(
                "DjangoCodecRegistry unavailable; skipping registration for %s",
                getattr(obj, "__name__", obj),
            )
            return

        origin = getattr(obj, "origin", None)
        bucket = getattr(obj, "bucket", None)
        base_name = getattr(obj, "name", None)

        if not (origin and bucket and base_name):
            log.debug(
                "Codec identity incomplete; skipping registration: origin=%r bucket=%r name=%r",
                origin,
                bucket,
                base_name,
            )
            return

        suffix = 1
        while True:
            try:
                # Register with explicit tuple identity
                Registry.register(origin, bucket, getattr(obj, "name", base_name), obj)
                log.info(
                    "django.codec.registered (%s, %s, %s) -> %s",
                    origin,
                    bucket,
                    getattr(obj, "name", base_name),
                    getattr(obj, "__name__", obj),
                )
                return
            except DuplicateCodecIdentityError:
                suffix += 1
                new_name = f"{base_name}-{suffix}"
                setattr(obj, "name", new_name)
                log.warning(
                    "Collision for django codec identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    origin,
                    bucket,
                    base_name,
                    origin,
                    bucket,
                    new_name,
                )
                # retry with updated name
            except Exception:  # pragma: no cover
                log.debug(
                    "Django codec registration error suppressed for %s",
                    getattr(obj, "__name__", obj),
                    exc_info=True,
                )
                return


class DjangoCodecDecorator(
    DjangoCodecRegistrationMixin,
    DjangoSimcoreIdentityMixin,
    _CoreCodecDecorator,
):
    """Django-aware codec decorator.

    MRO ensures:
      - `register` comes from DjangoCodecRegistrationMixin,
      - identity/tokens from DjangoSimcoreIdentityMixin,
      - class-only & base decorator behavior from _CoreCodecDecorator.
    """
    pass


# Ready-to-use instance for Django apps
codec = DjangoCodecDecorator()

__all__ = ["codec", "DjangoCodecDecorator", "DjangoCodecRegistrationMixin"]
