"""Shared decorators that register callbacks before an app exists."""

from __future__ import annotations

from typing import Any, Callable


def shared_service(name: str | None = None, **opts: Any):
    def decorator(func: Callable):
        raise RuntimeError("shared_service is not supported without service runners")

    return decorator

