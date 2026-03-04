# orchestrai/decorators/components/instruction_decorator.py
"""
Instruction decorator for registering BaseInstruction subclasses.

Supports both ``@instruction`` and ``@instruction(order=10)`` forms.
"""

from orchestrai.decorators.base import BaseDecorator
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

__all__ = ("InstructionDecorator",)


class InstructionDecorator(BaseDecorator):
    """Decorator for registering BaseInstruction subclasses."""

    default_domain = INSTRUCTIONS_DOMAIN
    log_category = "instructions"

    def get_registry(self):
        from orchestrai.registry.active_app import get_component_store
        store = get_component_store()
        if store is None:
            return None
        return store.registry(INSTRUCTIONS_DOMAIN)

    def bind_extras(self, cls, extras):
        order = extras.pop("order", getattr(cls, "order", 50))
        if not isinstance(order, int) or not (0 <= order <= 100):
            raise ValueError(f"order must be an integer 0-100, got {order!r}")
        cls.order = order
        cls.abstract = False

    def register(self, candidate):
        from orchestrai.instructions.base import BaseInstruction

        if not issubclass(candidate, BaseInstruction):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass "
                "BaseInstruction to use @instruction"
            )
        super().register(candidate)
