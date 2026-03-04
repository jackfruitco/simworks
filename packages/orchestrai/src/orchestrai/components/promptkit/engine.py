"""Minimal prompt engine compatibility shim."""

from __future__ import annotations

from typing import Any


class PromptEngine:
    """Compatibility shell for legacy prompt engine imports."""

    @staticmethod
    def render(_section: Any, _context: dict[str, Any] | None = None) -> str:
        return ""
