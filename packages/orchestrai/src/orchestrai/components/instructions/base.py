"""Base class for instruction mixins."""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar

from orchestrai.identity import IdentityMixin
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

__all__ = ["BaseInstruction"]


class BaseInstruction(IdentityMixin, ABC):
    """Identity-bearing instruction mixin used by service MRO."""

    DOMAIN: ClassVar[str] = INSTRUCTIONS_DOMAIN
    domain: ClassVar[str | None] = INSTRUCTIONS_DOMAIN
    abstract: ClassVar[bool] = True

    # Lower values are rendered first.
    order: ClassVar[int] = 50

    # Static instruction text for simple instructions.
    instruction: ClassVar[str | None] = None

    async def render_instruction(self, **ctx: Any) -> str | None:
        """Render instruction content for the owning service instance."""
        return self.instruction
