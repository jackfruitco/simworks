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
            app.services.register(service_name, func)

        connect_on_app_finalize(_attach)
        return Proxy(lambda: get_current_app().services.get(service_name))

    return decorator

