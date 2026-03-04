# orchestrai/decorators/__init__.py
"""Decorator facade (lazy imports to avoid cycles)."""

from __future__ import annotations

from .base import BaseDecorator


def __getattr__(name: str):
    if name == "service":
        from . import components as _components

        return getattr(_components, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseDecorator",
    "service",
]
