"""Compatibility schema base classes for legacy imports."""

from __future__ import annotations

from collections.abc import Iterable

from .base import BaseOutputItem, BaseOutputSchema


def sort_adapters(adapters: Iterable[object]) -> list[object]:
    """Sort adapters by optional `priority` (desc), preserving deterministic order."""
    return sorted(adapters, key=lambda adapter: int(getattr(adapter, "priority", 0)), reverse=True)


__all__ = ["BaseOutputItem", "BaseOutputSchema", "sort_adapters"]
