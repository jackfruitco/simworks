from __future__ import annotations

"""
Django-aware codec decorator (class-based; no factory functions).

This decorator composes the **core** codec decorator with the **Django** base
so that codec classes get a unified, Django-aware identity and are registered
in the Django codecs registry without mutating class attributes.

Key behaviors
-------------
- Identity derivation is delegated to the resolver selected by the mixin stack
  (here: `DjangoIdentityResolver` via `DjangoBaseDecorator`). That resolver:
  • infers `namespace` from (arg → class attr → AppConfig.label → module root → "default")
  • uses segment-aware name derivation and token stripping sourced from
    AppConfig / Django settings / core defaults (no stamping on the class)
- Domain default: `kind="codec"` unless explicitly provided.
- Registration: the resolved identity tuple3 is handed to the Django codecs
  registry (`simcore_ai_django.codecs.registry.codecs`). Collision policy is
  enforced by the registry (respecting `SIMCORE_COLLISIONS_STRICT` if configured).

Notes
-----
- No collision rewriting is performed here; registries own the policy.
- If you need dev-only rename-on-collision, implement that in the registry layer,
  not in decorators.
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
        """Return the Django codecs registry singleton (or None to skip registration)."""
        return codecs


# Ready-to-use decorator instances (short and namespaced aliases)
codec = DjangoCodecDecorator()
ai_codec = codec

__all__ = ["codec", "ai_codec", "DjangoCodecDecorator"]
