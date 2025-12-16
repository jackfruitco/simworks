"""Shared decorators that register callbacks before an app exists."""

from __future__ import annotations

from typing import Any, Callable

from ._state import get_current_app
from .finalize import connect_on_app_finalize
from .utils.proxy import Proxy


def shared_service(name: str | None = None, **opts: Any):
    def decorator(func: Callable):
        service_name = name or func.__name__

        def _attach(app):
            add_cb = getattr(app, "add_service_finalize_callback", None)
            if callable(add_cb):
                add_cb(lambda _app: app.register_service_runner(service_name, func))
                return

            app.register_service_runner(service_name, func)

        connect_on_app_finalize(_attach)
        return Proxy(lambda: get_current_app().service_runners.get(service_name))

    return decorator

