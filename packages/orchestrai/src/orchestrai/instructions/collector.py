"""Instruction collection helpers."""

from __future__ import annotations

from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN
from orchestrai.instructions.base import BaseInstruction

__all__ = ["collect_instructions"]


def collect_instructions(cls: type) -> list[type[BaseInstruction]]:
    """Collect instruction classes from MRO and return deterministic order."""

    found: list[type[BaseInstruction]] = []
    seen: set[type[BaseInstruction]] = set()

    for klass in cls.__mro__:
        if klass is cls:
            continue
        if klass in (object, BaseInstruction):
            continue
        if not isinstance(klass, type):
            continue
        if not issubclass(klass, BaseInstruction):
            continue
        domain = getattr(klass, "DOMAIN", None) or getattr(klass, "domain", None)
        if domain != INSTRUCTIONS_DOMAIN:
            continue
        if getattr(klass, "abstract", False):
            continue
        if klass in seen:
            continue
        seen.add(klass)
        found.append(klass)

    found.sort(key=lambda item: (getattr(item, "order", 50), item.__name__))
    return found
