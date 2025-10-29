# packages/simcore_ai/src/simcore_ai/promptkit/decorators.py
from __future__ import annotations

"""
Core (non-Django) Prompt Section decorator built on the class-based BaseDecorator.

This decorator is intentionally thin:
- Delegates identity derivation to the core IdentityResolver via BaseDecorator
- Applies the domain default `kind="prompt_section"` when arg/attr doesn't specify kind
- Does **not** register in core (get_registry() -> None); Django layer wires registries

No token collection or normalization logic lives here; that is owned by the resolver.
"""

from typing import Any, Optional, Type

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.identity.base import Identity


class PromptSectionRegistrationDecorator(BaseDecorator):
    """Core Prompt Section decorator: delegate to resolver; no registration in core."""

    def get_registry(self):  # core layer does not register prompt sections
        return None

    def derive_identity(
        self,
        cls: Type[Any],
        *,
        namespace: Optional[str],
        kind: Optional[str],
        name: Optional[str],
    ) -> tuple[Identity, dict[str, Any] | None]:
        """Use the base resolver but inject the domain default kind="prompt_section".

        Precedence becomes:
          - kind arg (if provided) → class attr `kind` (if provided) → "prompt_section"
        All other behavior (explicit vs derived name, stripping, normalization)
        is handled by the resolver.
        """
        effective_kind = kind if (isinstance(kind, str) and kind.strip()) else getattr(cls, "kind", None)
        if not (isinstance(effective_kind, str) and effective_kind.strip()):
            effective_kind = "prompt_section"

        identity, meta = self.resolver.resolve(
            cls,
            namespace=namespace,
            kind=effective_kind,
            name=name,
        )
        return identity, meta


# Ready-to-use decorator instances (short and namespaced aliases)
prompt_section = PromptSectionRegistrationDecorator()
ai_prompt_section = prompt_section

__all__ = ["prompt_section", "ai_prompt_section", "PromptSectionRegistrationDecorator"]
