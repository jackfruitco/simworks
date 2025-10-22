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
from typing import Any

from simcore_ai.codecs.decorators import CodecDecorator as _CoreCodecDecorator
from simcore_ai_django.decorators.mixins import DjangoSimcoreIdentityMixin

logger = logging.getLogger(__name__)


class DjangoCodecRegistrationMixin:
    """Override `register` to use the Django codec registry with collision suffixing."""

    def register(self, cls: type[Any], identity: tuple[str, str, str], **kwargs) -> None:
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
            logger.debug(
                "DjangoCodecRegistry unavailable; skipping registration for %s",
                getattr(cls, "__name__", cls),
            )
            return

        origin, bucket, name = identity

        # Ensure the resolved identity is reflected on the class prior to registration
        setattr(cls, "origin", origin)
        setattr(cls, "bucket", bucket)
        setattr(cls, "name", name)
        # Optional convenience string form if the class uses it
        setattr(cls, "identity", f"{origin}.{bucket}.{name}")

        if not (origin and bucket and name):
            logger.debug(
                "Codec identity incomplete; skipping registration: origin=%r bucket=%r name=%r",
                origin, bucket, name
            )
            return

        while True:
            try:
                Registry.register(origin, bucket, name, cls)
                logger.info(
                    "Registered Codec (%s, %s, %s) -> %s",
                    origin,
                    bucket,
                    name,
                    getattr(cls, "__name__", str(cls)),
                )
                return
            except DuplicateCodecIdentityError:
                # Bump only the name portion with a numeric suffix and retry
                new_name = self._bump_suffix(name)
                logger.warning(
                    "Collision for Codec identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    origin,
                    bucket,
                    name,
                    origin,
                    bucket,
                    new_name,
                )
                name = new_name
                setattr(cls, "name", name)
                setattr(cls, "identity", f"{origin}.{bucket}.{name}")



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
