# orchestrai/instructions/base.py
"""
Base instruction class for OrchestrAI.

Each instruction subclass represents a single system/developer instruction
that can be composed into service classes via MRO inheritance.
"""

from __future__ import annotations

from abc import ABC
from typing import ClassVar

from orchestrai.components.base import BaseComponent
from orchestrai.identity import IdentityMixin
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

__all__ = ["BaseInstruction"]


class BaseInstruction(IdentityMixin, BaseComponent, ABC):
    """Base class for instruction components.

    Each subclass represents a single system/developer instruction.
    Provides either a static ``instruction`` string or overrides
    ``render_instruction()`` for dynamic content.

    Mixed into service classes via MRO for composition.
    """

    DOMAIN: ClassVar[str] = INSTRUCTIONS_DOMAIN
    domain: ClassVar[str | None] = INSTRUCTIONS_DOMAIN
    abstract: ClassVar[bool] = True

    order: ClassVar[int] = 50
    required_context_keys: ClassVar[frozenset[str]] = frozenset()
    instruction: ClassVar[str | None] = None

    async def render_instruction(self) -> str | None:
        """Return instruction text. Override for dynamic content.

        When mixed into a service, ``self`` is the service instance,
        so ``self.context`` is accessible for dynamic rendering.
        """
        return self.instruction

    async def arun(self, *args, **kwargs):
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement arun; "
            "instructions are rendered via render_instruction()."
        )
