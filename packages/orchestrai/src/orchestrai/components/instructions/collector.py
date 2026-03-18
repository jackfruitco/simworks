"""Instruction collection helpers."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN
from orchestrai.identity.identity import Identity

if TYPE_CHECKING:
    pass

__all__ = ["collect_instructions"]

logger = logging.getLogger(__name__)


def _get_instruction_registry(app):
    """Return the instruction registry for modern or legacy app shims."""

    store = getattr(app, "component_store", None)
    if store is not None and hasattr(store, "registry"):
        return store.registry(INSTRUCTIONS_DOMAIN)

    components = getattr(app, "components", None)
    if components is not None and hasattr(components, "registry"):
        return components.registry(INSTRUCTIONS_DOMAIN)

    raise AttributeError("instruction_refs: active app has no instruction registry")


def _instruction_sort_name(instruction_cls: type[BaseInstruction]) -> str:
    """Return the stable instruction name used for deterministic ordering.

    Prefer explicit ``name`` (identity-stable for YAML and decorator-backed
    classes). Fall back to ``__name__`` for backwards compatibility.
    """

    declared_name = getattr(instruction_cls, "name", None)
    if isinstance(declared_name, str) and declared_name:
        return declared_name
    return instruction_cls.__name__


def collect_instructions(cls: type) -> list[type[BaseInstruction]]:
    """Return the ordered instruction classes for *cls*.

    Two modes are supported:

    1. **``instruction_refs`` mode** (preferred): If *cls* defines
       ``instruction_refs``, each entry is resolved against the instructions
       registry.  Accepted ref formats:

       - ``"namespace.group.ClassName"`` — 3-part identity ref (domain
         ``instructions`` is implicit).  **Preferred format.**
       - ``"domain.namespace.group.ClassName"`` — 4-part full identity label.

       The returned list is sorted by ``(order, name)`` where ``name`` prefers
       the explicit instruction identity name and falls back to ``__name__``.

    2. **MRO mode** (legacy): If ``instruction_refs`` is absent or ``None``,
       the MRO of *cls* is walked to collect non-abstract
       :class:`~orchestrai.components.instructions.base.BaseInstruction`
       subclasses, sorted by ``(order, name)``.

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

    Supports 3-part ``namespace.group.Name`` and 4-part ``domain.ns.group.Name``.
    """
    from orchestrai._state import get_current_app  # avoid import-time cycles

    app = get_current_app()
    if app is None:
        raise LookupError("instruction_refs: no active OrchestrAI app is available")
    registry = _get_instruction_registry(app)

    found: list[type[BaseInstruction]] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        instruction_cls = _resolve_single_ref(ref, registry, app=app)
        found.append(instruction_cls)

    found.sort(key=lambda c: (getattr(c, "order", 50), _instruction_sort_name(c)))
    return found


def _resolve_single_ref(ref: str, registry, *, app) -> type[BaseInstruction]:  # type: ignore[type-arg]
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
            _attempt_lazy_yaml_load(namespace=namespace, group=group, app=app)
            cls = registry.try_get(identity)
        if cls is None:
            _attempt_lazy_yaml_load(namespace=namespace, group=group, app=app)
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

    raise ValueError(
        f"instruction_refs: invalid ref format {ref!r}. "
        "Use 'namespace.group.ClassName' (3-part) or "
        "'domain.namespace.group.ClassName' (4-part). "
        f"Available labels: {sorted(registry.labels())}"
    )


def _attempt_lazy_yaml_load(*, namespace: str, group: str, app) -> None:
    """Attempt lazy YAML load for unresolved instruction refs in discovery-light setups."""

    from orchestrai.instructions.yaml_loader import load_yaml_instructions

    module_name = f"apps.{namespace}.orca.instructions"
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return

    if spec is None or spec.submodule_search_locations is None:
        return

    for location in spec.submodule_search_locations:
        yaml_path = Path(location) / f"{group}.yaml"
        if yaml_path.exists():
            try:
                load_yaml_instructions(yaml_path, app=app)
            except Exception:
                return
            return


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

    found.sort(key=lambda item: (getattr(item, "order", 50), _instruction_sort_name(item)))
    return found
