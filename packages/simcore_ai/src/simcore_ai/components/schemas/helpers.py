# simcore_ai/components/schemas/helpers.py
"""
This module provides helper utility functions for handling adapters in the
AI components schema.

It focuses on facilitating operations like sorting adapters for use
in AI components by their defined priority.
"""
from collections.abc import Iterable
from .adapters import BaseAdapter

__all__ = ("sort_adapters",)


def sort_adapters(adapters: Iterable[BaseAdapter]) -> list[BaseAdapter]:
    """Sorts adapters by priority (order)."""
    return sorted(adapters, key=lambda adapter: adapter.order)
