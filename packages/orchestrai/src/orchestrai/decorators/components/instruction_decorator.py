"""Core instruction decorator."""

from __future__ import annotations

from typing import Any

from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.decorators.base import BaseDecorator
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN
from orchestrai.registry import ComponentRegistry, instructions as instructions_registry

__all__ = ("InstructionDecorator",)


class InstructionDecorator(BaseDecorator):
    """Decorator specialized for ``BaseInstruction`` subclasses."""

    default_domain = INSTRUCTIONS_DOMAIN
    log_category = "instructions"

    def derive_identity(
        self,
        cls: type[Any],
        *,
        domain: str | None,
        namespace: str | None,
        group: str | None,
        name: str | None,
    ):
        resolved_domain = domain or INSTRUCTIONS_DOMAIN
        return super().derive_identity(
            cls,
            domain=resolved_domain,
            namespace=namespace,
            group=group,
            name=name or cls.__name__,
        )

    def get_registry(self) -> ComponentRegistry:
        return instructions_registry

    def bind_extras(self, cls: type[Any], extras: dict[str, Any]) -> None:
        order = extras.pop("order", None)
        if order is None:
            order = getattr(cls, "order", 50)
        if not isinstance(order, int):
            raise ValueError(f"{cls.__module__}.{cls.__name__} order must be an integer")
        if order < 0 or order > 100:
            raise ValueError(f"{cls.__module__}.{cls.__name__} order must be between 0 and 100")

        cls.order = order
        cls.abstract = False
        # Pin identity ``name`` to the raw class name so IdentityMixin never
        # applies token stripping (e.g. "PatientNameInstruction" must not
        # silently become "PatientName").  This keeps instruction_refs
        # deterministic and matching the Python/YAML source exactly.
        cls.name = cls.__name__

    def register(self, candidate: type[Any]) -> None:
        if not issubclass(candidate, BaseInstruction):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass "
                "BaseInstruction to use @instruction"
            )
        super().register(candidate)
