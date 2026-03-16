"""Instruction collection helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
import warnings

from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN
from orchestrai.identity.identity import Identity

if TYPE_CHECKING:
    pass

__all__ = ["collect_instructions"]

logger = logging.getLogger(__name__)


def collect_instructions(cls: type) -> list[type[BaseInstruction]]:
    """Return the ordered instruction classes for *cls*.

    Two modes are supported:

    1. **``instruction_refs`` mode** (preferred): If *cls* defines
       ``instruction_refs``, each entry is resolved against the instructions
       registry.  Accepted ref formats:

       - ``"namespace.group.ClassName"`` — 3-part identity ref (domain
         ``instructions`` is implicit).  **Preferred format.**
       - ``"domain.namespace.group.ClassName"`` — 4-part full identity label.
       - ``"ClassName"`` — bare class name (deprecated; O(n) scan; emits a
         ``DeprecationWarning``).

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
    """Resolve a list of instruction ref strings to classes.

    Supports 3-part ``namespace.group.Name``, 4-part ``domain.ns.group.Name``,
    and bare ``Name`` refs (deprecated).
    """
    from orchestrai._state import get_current_app  # avoid import-time cycles

    app = get_current_app()
    registry = app.components.registry(INSTRUCTIONS_DOMAIN)

    found: list[type[BaseInstruction]] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        instruction_cls = _resolve_single_ref(ref, registry)
        found.append(instruction_cls)

    found.sort(key=lambda c: (getattr(c, "order", 50), c.__name__))
    return found


def _resolve_single_ref(ref: str, registry) -> type[BaseInstruction]:  # type: ignore[type-arg]
    """Resolve one ref string to an instruction class.

    Raises ``ValueError`` with a diagnostic message if the ref cannot be found.
    """
    dot_count = ref.count(".")

    if dot_count == 2:
        # 3-part: namespace.group.name
        namespace, group, name = ref.split(".", 2)
        identity = Identity(
            domain=INSTRUCTIONS_DOMAIN,
            namespace=namespace,
            group=group,
            name=name,
        )
        cls = registry.try_get(identity)
        if cls is None:
            raise ValueError(
                f"instruction_refs: no instruction found for {ref!r} "
                f"(resolved as {identity.label!r}). "
                f"Available labels: {sorted(registry.labels())}"
            )
        return cls  # type: ignore[return-value]

    if dot_count == 3:
        # 4-part: domain.namespace.group.name
        domain, namespace, group, name = ref.split(".", 3)
        identity = Identity(domain=domain, namespace=namespace, group=group, name=name)
        cls = registry.try_get(identity)
        if cls is None:
            raise ValueError(
                f"instruction_refs: no instruction found for {ref!r} "
                f"(resolved as {identity.label!r}). "
                f"Available labels: {sorted(registry.labels())}"
            )
        return cls  # type: ignore[return-value]

    # Bare name (no dots) — deprecated fallback.
    warnings.warn(
        f"instruction_refs: bare name {ref!r} is deprecated. "
        "Use a 3-part 'namespace.group.ClassName' ref instead. "
        "Bare names are O(n) and non-unique across namespaces.",
        DeprecationWarning,
        stacklevel=6,
    )
    cls = registry.find_by_name(ref)
    if cls is None:
        raise ValueError(
            f"instruction_refs: no instruction named {ref!r} found. "
            f"Available labels: {sorted(registry.labels())}"
        )
    return cls  # type: ignore[return-value]


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
