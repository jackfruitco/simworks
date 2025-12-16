"""Resolution helpers with branch tracing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class ResolutionBranch(Generic[T]):
    """A single resolution attempt/branch."""

    name: str
    value: T | None
    reason: str | None = None
    identity: str | None = None
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ResolutionResult(Generic[T]):
    """Aggregate result of a resolver with branch history."""

    value: T | None
    selected: ResolutionBranch[T]
    branches: list[ResolutionBranch[T]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.selected not in self.branches:
            self.branches.insert(0, self.selected)

    @property
    def branch(self) -> str:
        return self.selected.name

    def context(self, prefix: str) -> dict[str, object]:
        """Return a shallow context mapping for tracing."""

        ctx: dict[str, object] = {
            f"{prefix}.branch": self.selected.name,
            f"{prefix}.reason": self.selected.reason or "",
            f"{prefix}.identity": self.selected.identity or "<none>",
        }

        # Preserve compact branch history for debugging (branch:identity pairs)
        history: list[str] = []
        for br in self.branches:
            label = br.identity or "<none>"
            history.append(f"{br.name}:{label}")
        ctx[f"{prefix}.branches"] = " | ".join(history)
        return ctx


__all__ = [
    "ResolutionBranch",
    "ResolutionResult",
]
