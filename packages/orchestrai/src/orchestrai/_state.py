"""Lightweight current-application tracking.

This module keeps import-time side effects to a minimum. It uses a
``ContextVar`` to hold the active application, providing predictable
nesting semantics via :func:`push_current_app`.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generator

from .utils.proxy import Proxy

_current_app: ContextVar[object | None] = ContextVar("orchestrai_current_app", default=None)
_default_app: object | None = None


def _build_default_app() -> object:
    """Create the lazily constructed default app.

    Separated for import-safety: the import of :mod:`orchestrai.app` happens
    only when no app has been set explicitly.
    """
    from .app import OrchestrAI

    return OrchestrAI("default")


def get_current_app():
    """Return the active app, creating a default one if none is set."""
    app = _current_app.get()
    if app is None:
        global _default_app
        if _default_app is None:
            _default_app = _build_default_app()
        app = _default_app
        set_current_app(app)
    return app


def set_current_app(app: object) -> None:
    _current_app.set(app)


@contextmanager
def push_current_app(app: object) -> Generator[object, None, None]:
    token = _current_app.set(app)
    try:
        yield app
    finally:
        _current_app.reset(token)


current_app = Proxy(get_current_app)

__all__ = ["current_app", "get_current_app", "push_current_app", "set_current_app"]
