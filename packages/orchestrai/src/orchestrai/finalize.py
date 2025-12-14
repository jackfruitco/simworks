"""Finalize callback registry used by shared decorators."""

from __future__ import annotations

from typing import Callable, List


_finalize_callbacks: List[Callable[[object], None]] = []


def connect_on_app_finalize(callback: Callable[[object], None]) -> None:
    _finalize_callbacks.append(callback)


def consume_finalizers():
    callbacks = list(_finalize_callbacks)
    _finalize_callbacks.clear()
    return callbacks

