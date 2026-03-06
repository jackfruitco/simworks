# orchestrai/decorators/__init__.py
"""Decorator facade (lazy imports to avoid cycles)."""

from __future__ import annotations

from .base import BaseDecorator


def __getattr__(name: str):
    if name in {"instruction", "service"}:
        from . import components as _components

        return getattr(_components, name)
    if name == "orca":
        return orca
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _OrcaDecorators:
    """Lazy namespace for core decorators."""

    @property
    def service(self):
        from . import components as _components

        return _components.service

    @property
    def instruction(self):
        from . import components as _components

        return _components.instruction


orca = _OrcaDecorators()

__all__ = [
    "BaseDecorator",
    "instruction",
    "orca",
    "service",
]
