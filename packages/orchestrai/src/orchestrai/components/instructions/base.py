"""Base class for instruction mixins."""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar

from orchestrai.identity import IdentityMixin
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

__all__ = ["BaseInstruction", "MissingRequiredContextError"]


class MissingRequiredContextError(ValueError):
    """Raised when a required context variable is absent before rendering.

    Attributes
    ----------
    instruction_name:
        ``__name__`` of the instruction class that raised.
    missing_keys:
        Variables that were declared required but absent from context.
    available_keys:
        Keys that *were* present in the context (useful for debugging).
    """

    def __init__(
        self,
        instruction_name: str,
        missing_keys: list[str],
        available_keys: list[str],
    ) -> None:
        self.instruction_name = instruction_name
        self.missing_keys = missing_keys
        self.available_keys = available_keys
        super().__init__(
            f"Instruction {instruction_name!r} requires context "
            f"keys {missing_keys!r} but they are absent. "
            f"Available: {sorted(available_keys)!r}"
        )


class BaseInstruction(IdentityMixin, ABC):
    """Identity-bearing instruction mixin used by service MRO."""

    DOMAIN: ClassVar[str] = INSTRUCTIONS_DOMAIN
    domain: ClassVar[str | None] = INSTRUCTIONS_DOMAIN
    abstract: ClassVar[bool] = True

    # Lower values are rendered first.
    order: ClassVar[int] = 50

    # Static instruction text for simple instructions.
    instruction: ClassVar[str | None] = None

    # Declare variables that must be present in context before rendering.
    # Validated by _validate_context(); YAML instructions set this from the
    # ``required_variables`` key; Python instructions may set it manually.
    required_variables: ClassVar[tuple[str, ...]] = ()

    # Document optional ${variable} placeholders used in the instruction
    # template.  These are substituted with an empty string when absent —
    # declaring them here makes the contract explicit and suppresses drift
    # warnings at load time.  No runtime behaviour change.
    optional_variables: ClassVar[tuple[str, ...]] = ()

    def _validate_context(self, context: dict[str, Any]) -> None:
        """Raise MissingRequiredContextError if any required_variables are absent.

        Call this at the top of render_instruction() in subclasses that declare
        required_variables.  The YAML loader does this automatically for YAML
        instructions; Python instruction authors may call it manually.
        """
        if not self.required_variables:
            return
        missing = [k for k in self.required_variables if k not in context]
        if missing:
            raise MissingRequiredContextError(
                instruction_name=self.__class__.__name__,
                missing_keys=missing,
                available_keys=list(context.keys()),
            )

    async def render_instruction(self, **ctx: Any) -> str | None:
        """Render instruction content for the owning service instance."""
        return self.instruction
