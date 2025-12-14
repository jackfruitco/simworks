"""Lightweight proxy utilities.

This module intentionally avoids pulling in heavy dependencies so that it can
be safely imported early in the application lifecycle. The implementation is
inspired by Celery's ``Proxy`` helper and forwards attribute access, item
access, and calls to the underlying object returned by the provided resolver
function.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar


class _CallableResolver(Protocol):
    def __call__(self) -> Any:  # pragma: no cover - Protocol signature only
        ...


T = TypeVar("T")


class Proxy:
    """Proxy that defers all operations to the target resolved at access time."""

    __slots__ = ("_resolver",)

    def __init__(self, resolver: _CallableResolver) -> None:
        self._resolver = resolver

    def _get_current(self) -> Any:
        return self._resolver()

    # Attribute access -------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_current(), name)

    # Item access ------------------------------------------------------
    def __getitem__(self, key: Any) -> Any:
        return self._get_current()[key]

    # Callable ---------------------------------------------------------
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_current()(*args, **kwargs)

    # Representation ---------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Proxy({self._get_current()!r})"


def maybe_evaluate(value: T | Proxy) -> T:
    """Resolve the value if it's a :class:`Proxy`, otherwise return unchanged."""

    if isinstance(value, Proxy):
        return value._get_current()
    return value
