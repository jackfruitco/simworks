"""Minimal prompt section compatibility types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class Prompt:
    """Simple prompt container for legacy type references."""

    text: str = ""


class PromptSection:
    """Legacy compatibility base for prompt sections."""

    abstract: ClassVar[bool] = True

    @classmethod
    def render(cls, context: dict[str, Any] | None = None) -> str:
        return ""
