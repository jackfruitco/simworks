"""Instruction collection helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN

if TYPE_CHECKING:
    pass

__all__ = ["collect_instructions"]

logger = logging.getLogger(__name__)


def collect_instructions(cls: type) -> list[type[BaseInstruction]]:
    """Return the ordered instruction classes for *cls*.

    Two modes are supported:

    1. **``instruction_refs`` mode** (new): If *cls* defines a non-empty
       ``instruction_refs`` class attribute (a list of class-name strings),
       each name is resolved against the instructions registry via
       :meth:`~orchestrai.registry.base.ComponentRegistry.find_by_name`.
       The returned list is sorted by ``(order, __name__)``.

    2. **MRO mode** (legacy): If ``instruction_refs`` is absent or ``None``,
       the MRO of *cls* is walked to collect non-abstract
       :class:`~orchestrai.components.instructions.base.BaseInstruction`
       subclasses, sorted by ``(order, __name__)``.

    Both modes guarantee a deterministic, deduplicated result.
    """
    refs = getattr(cls, "instruction_refs", None)
    if refs is not None:
        return _resolve_instruction_refs(refs)
    return _collect_from_mro(cls)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_instruction_refs(refs: list[str]) -> list[type[BaseInstruction]]:
    """Resolve a list of instruction class-name strings to classes."""
    from orchestrai._state import get_current_app  # avoid import-time cycles

    app = get_current_app()
    registry = app.components.registry(INSTRUCTIONS_DOMAIN)

    found: list[type[BaseInstruction]] = []
    seen: set[str] = set()
    for name in refs:
        if name in seen:
            continue
        seen.add(name)
        instruction_cls = registry.find_by_name(name)
        if instruction_cls is None:
            raise ValueError(
                f"instruction_refs: no instruction named {name!r} found in the "
                f"instructions registry.  Available: {registry.keys(as_csv=True)}"
            )
        found.append(instruction_cls)

    found.sort(key=lambda c: (getattr(c, "order", 50), c.__name__))
    return found


def _collect_from_mro(cls: type) -> list[type[BaseInstruction]]:
    """Walk the MRO of *cls* and collect non-abstract BaseInstruction subclasses."""
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
