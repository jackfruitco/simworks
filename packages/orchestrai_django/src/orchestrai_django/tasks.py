# orchestrai_django/tasks.py
"""Minimal Django Tasks shims used by the service runner."""

from __future__ import annotations

from typing import Any

_ENQUEUED: list[dict[str, Any]] = []


def enqueue_service(**payload: Any) -> dict[str, Any]:
    record = dict(payload)
    _ENQUEUED.append(record)
    return record


def get_service_status(**payload: Any) -> dict[str, Any]:
    return {"status": "queued", **payload}


__all__ = ["enqueue_service", "get_service_status"]
