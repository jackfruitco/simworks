"""Finalize callback registry used by shared decorators."""

from __future__ import annotations

from typing import Callable, List


_finalize_callbacks: List[Callable[[object], None]] = []


def connect_on_app_finalize(callback: Callable[[object], None]) -> None:
    _finalize_callbacks.append(callback)


def consume_finalizers():
    """Return registered finalize callbacks without clearing global storage."""

    return list(_finalize_callbacks)

