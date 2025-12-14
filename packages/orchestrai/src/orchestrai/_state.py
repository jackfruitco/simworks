"""Thread-local application state inspired by Celery.

Importing this module must remain lightweight to allow ``from orchestrai import
current_app`` without triggering expensive initialization.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

from .utils.proxy import Proxy


_state = threading.local()
_fallback_app = None


def _get_fallback_app():
    global _fallback_app
    if _fallback_app is None:
        from .app import OrchestrAI

        _fallback_app = OrchestrAI("default")
    return _fallback_app


def get_current_app():
    """Return the current app, creating a fallback default if missing."""

    app = getattr(_state, "current_app", None)
    if app is None:
        app = _get_fallback_app()
        set_current_app(app)
    return app


def set_current_app(app) -> None:
    _state.current_app = app


@contextmanager
def push_current_app(app) -> Generator:
    previous = getattr(_state, "current_app", None)
    set_current_app(app)
    try:
        yield app
    finally:
        if previous is not None:
            set_current_app(previous)
        else:
            _state.__dict__.pop("current_app", None)


current_app = Proxy(get_current_app)

