# packages/simcore_ai/src/simcore_ai/codecs/decorators.py
from __future__ import annotations

"""
Core (non-Django) codec decorator built on the class-based BaseDecorator.

Goals (v3):
- Centralize identity logic in the Identity package & resolvers
- Use unified registry API: `register(...)` (strict + idempotent) which calls
  private `._register(...)` under the hood. No legacy maybe_register paths.

Behavior:
- Derives identity via the resolver with domain default `kind="codec"` when
  not explicitly provided via arg/attr
- Registers the class in the **core** CodecRegistry (idempotent). The Django
  layer may additionally mirror/bridge to its registry if desired, but this
  core decorator does register now to satisfy the unified plan.
- No token collection or normalization lives here; that is owned by the resolver.
"""

from typing import Any, Optional, Type

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.identity.base import Identity
from simcore_ai.codecs.registry import CodecRegistry


class CodecRegistrationDecorator(BaseDecorator):
    """Core codec decorator: resolve identity, then register in the core registry.

    This class is intentionally thin: all identity parsing/validation is
    delegated to the configured resolver (from BaseDecorator). Registration
    is routed through `CodecRegistry.register(...)` which is strict but
    idempotent (re-registering the same class/key is a no-op).
    """

    # --- registry wiring -------------------------------------------------
    def get_registry(self):  # type: ignore[override]
        return CodecRegistry

    # --- identity derivation --------------------------------------------
    def derive_identity(
            self,
            cls: Type[Any],
            *,
            namespace: Optional[str],
            kind: Optional[str],
            name: Optional[str],
    ) -> tuple[Identity, dict[str, Any] | None]:
        """Use the base resolver but inject the domain default kind="codec".

        Precedence becomes:
          - kind arg (if provided) → class attr `kind` (if provided) → "codec"
        All other behavior (explicit vs derived name, stripping, normalization)
        is handled by the resolver.
        """
        effective_kind = kind if (isinstance(kind, str) and kind.strip()) else getattr(cls, "kind", None)
        if not (isinstance(effective_kind, str) and effective_kind.strip()):
            effective_kind = "codec"

        identity, meta = self.resolver.resolve(
            cls,
            namespace=namespace,
            kind=effective_kind,
            name=name,
        )
        return identity, meta


# Ready-to-use decorator instances (short and namespaced aliases)
codec = CodecRegistrationDecorator()
ai_codec = codec

__all__ = ["codec", "ai_codec", "CodecRegistrationDecorator"]
