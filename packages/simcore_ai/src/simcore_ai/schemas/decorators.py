# simcore_ai/schemas/decorators.py
from __future__ import annotations

"""
Core (non-Django) Schema decorator built on the class-based BaseDecorator.

This decorator is intentionally thin:
- Delegates identity derivation to the core IdentityResolver via BaseDecorator
- Applies the domain default `kind="schema"` when arg/attr doesn't specify kind
- Does **not** register in core (get_registry() -> None); Django layer wires registries

No token collection or normalization logic lives here; that is owned by the resolver.
"""

from typing import Any, Optional, Type

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.identity.base import Identity
import logging

logger = logging.getLogger(__name__)


class SchemaRegistrationDecorator(BaseDecorator):
    """Core Schema decorator: delegates identity derivation; no core registration."""

    def get_registry(self) -> None:  # core layer does not register schemas
        return None

    def derive_identity(
            self,
            cls: Type[Any],
            *,
            namespace: Optional[str],
            kind: Optional[str],
            name: Optional[str],
    ) -> tuple[Identity, dict[str, Any] | None]:
        """Use the base resolver but inject the domain default kind='schema'.

        Precedence becomes:
          - kind arg (if provided) → class attr `kind` (if provided) → 'schema'
        All other behavior (explicit vs. derived name, stripping, normalization)
        is handled by the resolver.
        """
        # Respect explicit arg or class attr, else default to 'schema'
        effective_kind = kind if (isinstance(kind, str) and kind.strip()) else getattr(cls, "kind", None)
        if not (isinstance(effective_kind, str) and effective_kind.strip()):
            effective_kind = "schema"

        identity, meta = self.resolver.resolve(
            cls,
            namespace=namespace,
            kind=effective_kind,
            name=name,
        )

        # Tiny debug hook (safe & optional)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "schema.decorator.derive_identity: %s -> %s (kind=%r, defaulted=%s)",
                getattr(cls, "__name__", str(cls)),
                identity.as_str,
                effective_kind,
                effective_kind == "schema" and (kind is None and getattr(cls, "kind", None) in (None, "")),
            )

        return identity, meta


# Ready-to-use decorator instances (short and namespaced aliases)
schema: SchemaRegistrationDecorator = SchemaRegistrationDecorator()
ai_schema: SchemaRegistrationDecorator = schema

__all__ = ["schema", "ai_schema", "SchemaRegistrationDecorator"]
