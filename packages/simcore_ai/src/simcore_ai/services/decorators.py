# packages/simcore_ai/src/simcore_ai/services/decorators.py
from __future__ import annotations

"""
Core (non-Django) Service decorator built on the class-based BaseDecorator.

This module defines the **core** `llm_service` decorator using the shared,
framework-agnostic `BaseDecorator`. It is responsible only for:

- deriving a finalized Identity (namespace, kind, name) via the core resolver
  with the domain default `kind="service"` (when neither arg nor class attr
  provide a kind),
- attaching the identity to the decorated class as:
    * cls.identity      -> (namespace, kind, name) tuple
    * cls.identity_obj  -> Identity dataclass instance
- deferring registration: in the core package, `get_registry()` returns None,
  so decoration skips registration (Django layer wires registries and policy).

IMPORTANT:
- No Django imports here.
- No collision handling; that lives in the Django registries.
- No token collection here; stripping/normalization live in the resolver.
"""

from typing import Any, Optional, Type

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.identity.base import Identity


class ServiceRegistrationDecorator(BaseDecorator):
    """Core Service decorator: delegate to resolver; no registration in core."""

    def get_registry(self):  # core layer does not register services
        return None

    def derive_identity(
            self,
            cls: Type[Any],
            *,
            namespace: Optional[str],
            kind: Optional[str],
            name: Optional[str],
    ) -> tuple[Identity, dict[str, Any] | None]:
        """Use the base resolver but inject the domain default kind="service".

        Precedence becomes:
          - kind arg (if provided) → class attr `kind` (if provided) → "service"
        All other behavior (explicit vs derived name, stripping, normalization)
        is handled by the resolver.
        """
        # If neither decorator arg nor class attribute specify kind, default to "service".
        effective_kind = kind if (isinstance(kind, str) and kind.strip()) else getattr(cls, "kind", None)
        if not (isinstance(effective_kind, str) and effective_kind.strip()):
            effective_kind = "service"

        identity, meta = self.resolver.resolve(
            cls,
            namespace=namespace,
            kind=effective_kind,
            name=name,
        )
        return identity, meta


# Ready-to-use decorator instances (short and namespaced aliases)
llm_service = ServiceRegistrationDecorator()
ai_service = llm_service

__all__ = ["llm_service", "ai_service", "ServiceRegistrationDecorator"]
