# packages/simcore_ai_django/src/simcore_ai_django/codecs/decorators.py
from __future__ import annotations

"""
Django-aware codec decorator (class-based, no factories).

This decorator composes the core domain decorator with the Django-aware base to:

- derive a finalized Identity `(namespace, kind, name)` using Django-aware
  namespace resolution (AppConfig label → app name → module root) and
  name-only token stripping from AppConfig/global settings,
- set the domain default `kind="codec"`,
- register the class with the Django codecs registry (`codecs`), which
  enforces duplicate vs collision policy controlled by `SIMCORE_COLLISIONS_STRICT`.

No collision rewriting is performed here; registries own policy. If you want to
opt-in to dev-only rename-on-collision, override `allow_collision_rewrite()` in
this subclass to return True (recommended OFF in production).
"""

from typing import Any

from simcore_ai.codecs.decorators import (
    CodecRegistrationDecorator as CoreCodecDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator
from simcore_ai_django.codecs.registry import codecs


class DjangoCodecDecorator(DjangoBaseDecorator, CoreCodecDecorator):
    """Django-aware codec decorator: identity via DjangoBaseDecorator; registry wired here."""

    # Domain default for kind
    default_kind = "codec"

    def get_registry(self) -> Any | None:
        """Return the Django codecs registry singleton."""
        return codecs


# Ready-to-use decorator instances (short and namespaced aliases)
codec = DjangoCodecDecorator()
ai_codec = codec

__all__ = ["codec", "ai_codec", "DjangoCodecDecorator"]
