"""Minimal prompt plan compatibility shim."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptSectionSpec:
    section: Any


@dataclass
class PromptPlan:
    sections: list[Any] = field(default_factory=list)

    @classmethod
    def from_sections(cls, sections: list[Any]) -> PromptPlan:
        return cls(sections=list(sections))
