# orchestrai/promptkit/plans.py


from ...identity import Identity

"""
Prompt plans.

This module defines lightweight types to represent a *plan* of prompt sections
to be assembled by the PromptEngine. A plan is essentially an ordered list of
`PromptSection` classes or instances along with optional context/meta intended
for tracing and downstream observability.

Design goals:
- Keep it backend-agnostic and app-agnostic (no Django dependencies here).
- Accept either section *classes* (preferred) or *instances*.
- Offer helpful debugging descriptions when a non-section sneaks into the plan.
- Defer any registry-based resolution of identity strings to higher layers
  (apps, registries, or resolvers), to avoid tight coupling.

For now we do not implement confidence scoring or automatic selection logic.
Plans are either provided explicitly by services or (when absent) the service
falls back to a single section that matches the service identity.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Union
import logging

from .base import PromptSection

logger = logging.getLogger(__name__)

__all__ = [
    "PromptSectionSpec",
    "describe_section",
    "PromptPlan",
]

# A section spec may be a section class or an instance.
PromptSectionSpec = Union[type[PromptSection], PromptSection]


def _is_section_class(obj: object) -> bool:
    """Return True if obj is a PromptSection subclass (not an instance)."""
    try:
        return isinstance(obj, type) and issubclass(obj, PromptSection)
    except Exception:
        return False


def _is_section_instance(obj: object) -> bool:
    """Return True if obj is a PromptSection instance."""
    return isinstance(obj, PromptSection)


def describe_section(sec: object) -> str:
    """
    Render a human-friendly description of a section spec for debug logs
    and error input. This is intentionally resilient and avoids raising.

    Examples:
        - Class: "<class> chatlab.patient.initial (order=10)"
        - Instance: "<instance> chatlab.patient.initial (order=10)"
        - Other: "<invalid> dict keys=['x','y']"
    """
    try:
        if _is_section_class(sec):
            cls: type[PromptSection] = sec  # type: ignore[assignment]
            weight = getattr(cls, "order", None)
            return f"<class> {cls.identity.as_str} (order={weight})"
        if _is_section_instance(sec):
            inst: PromptSection = sec  # type: ignore[assignment]
            ident_str = inst.identity.to_string()
            return f"<instance> {ident_str} (order={inst.weight})"
        # Fallback: non-section, provide some shape
        if isinstance(sec, dict):
            return f"<invalid> dict keys={sorted(sec.keys())!r}"
        if isinstance(sec, (list, tuple)):
            return f"<invalid> {type(sec).__name__} len={len(sec)}"
        return f"<invalid> {type(sec).__name__}"
    except Exception as e:
        return f"<uninspectable: {type(e).__name__}: {e}>"


@dataclass(slots=True)
class PromptPlan:
    """
    An ordered collection of PromptSection specs (classes or instances) plus
    optional context/meta. The PromptEngine consumes a plan to produce a final
    `Prompt`.

    Notes:
        - Items are normalized/validated on mutation.
        - We deliberately do not resolve identity strings here; higher layers
          (e.g., apps or registries) can build a PromptPlan with resolved
          classes before passing it to the engine.
    """

    items: list[PromptSectionSpec] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    # ---------- construction helpers -------------------------------------

    @classmethod
    def empty(cls) -> "PromptPlan":
        return cls()

    @classmethod
    def from_sections(
            cls,
            sections: Iterable[PromptSectionSpec],
            *,
            context: dict[str, Any] | None = None,
            meta: dict[str, Any] | None = None,
    ) -> "PromptPlan":
        """Get PromptPlan object from list of PromptSections."""
        plan = cls(context=dict(context or {}), meta=dict(meta or {}))
        plan.add_many(sections)
        return plan

    @classmethod
    def from_any(
        cls,
        sections: Iterable[PromptSectionSpec | str],
        *,
        context: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> "PromptPlan":
        resolved: list[PromptSectionSpec] = []

        for raw in sections:
            sec = raw

            # Already a PromptSection instance or class
            if _is_section_class(sec):
                logger.debug("PromptPlan.from_any: using section class %r", sec)
                resolved.append(sec)
                continue

            # Try identity resolution USING THE CLASS, NOT A STRING
            cand = Identity.resolve.try_for_(PromptSection, sec)
            if cand is None:
                logger.warning(
                    "PromptPlan.from_any: could not resolve prompt section from input %r",
                    raw,
                )
                continue

            resolved.append(cand)

        if not resolved:
            # Use f-string or wrap `sections` in a 1-tuple to avoid TypeError
            raise ValueError(
                f"No valid prompt sections resolved from input: {sections!r}"
            )

        return cls.from_sections(sections=resolved, context=context, meta=meta)

    # ---------- core operations ------------------------------------------

    def add(self, spec: PromptSectionSpec) -> None:
        """Add a single section spec after validating its shape."""
        if not (_is_section_class(spec) or _is_section_instance(spec)):
            desc = describe_section(spec)
            raise TypeError(f"PromptPlan.add() expected a PromptSection class or instance, got {desc}")
        self.items.append(spec)

    def add_many(self, specs: Iterable[PromptSectionSpec]) -> None:
        """Add many section specs, validating each one."""
        for s in specs:
            self.add(s)

    def extend(self, specs: Iterable[PromptSectionSpec]) -> None:  # alias
        self.add_many(specs)

    def validate(self) -> None:
        """Validate that all items are section classes or instances."""
        for s in self.items:
            if not (_is_section_class(s) or _is_section_instance(s)):
                desc = describe_section(s)
                raise TypeError(f"PromptPlan.validate() found invalid item: {desc}")

    def to_debug_list(self) -> list[str]:
        """Return a list of friendly item descriptions for debugging."""
        return [describe_section(s) for s in self.items]

    # ---------- iteration / container protocol ---------------------------

    def __iter__(self) -> Iterator[PromptSectionSpec]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    # ---------- convenience ----------------------------------------------

    def with_context(self, **more: Any) -> "PromptPlan":
        """Return a new plan with context merged (shallow copy)."""
        new = PromptPlan(items=list(self.items), context=dict(self.context), meta=dict(self.meta))
        new.context.update(more)
        return new

    def copy(self) -> "PromptPlan":
        """Shallow copy of the plan."""
        return PromptPlan(items=list(self.items), context=dict(self.context), meta=dict(self.meta))

    # ---------- engine integration ---------------------------------------

    def as_engine_input(self) -> list[PromptSectionSpec]:
        """
        The engine accepts a list of section classes or instances.
        Return the raw validated list (raises if invalid).
        """
        self.validate()
        return list(self.items)
