# orchestrai/instructions/collector.py
"""
Instruction collector for service classes.

Walks the MRO of a class to find all concrete BaseInstruction subclasses
and returns them sorted by ``order`` ascending (lower=first).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseInstruction

__all__ = ["collect_instructions"]


def collect_instructions(cls: type) -> list[type[BaseInstruction]]:
    """Walk MRO, find BaseInstruction subclasses, sort by order ascending."""
    from .base import BaseInstruction

    seen: set[type] = set()
    instructions: list[type[BaseInstruction]] = []

    for klass in cls.__mro__:
        if klass is BaseInstruction or klass is object:
            continue
        if (
            isinstance(klass, type)
            and issubclass(klass, BaseInstruction)
            and klass not in seen
            and not getattr(klass, "abstract", False)
        ):
            seen.add(klass)
            instructions.append(klass)

    instructions.sort(key=lambda c: (c.order, c.__name__))
    return instructions
