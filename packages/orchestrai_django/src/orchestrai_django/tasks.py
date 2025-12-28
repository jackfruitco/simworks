# orchestrai_django/tasks.py
"""Minimal Django Tasks shims used by the service runner."""

# NOTE:
# This module is a thin, serializable boundary between OrchestrAI service runners
# and Django Tasks. It intentionally avoids passing Python objects (classes,
# callables) so the payload can be safely queued and executed out-of-process.

from __future__ import annotations

from typing import Any

_ENQUEUED: list[dict[str, Any]] = []


def enqueue_service(
    *,
    service_path: str,
    service_kwargs: dict[str, Any],
    phase: str,
    runner_name: str | None = None,
    runner_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "service_path": service_path,
        "service_kwargs": dict(service_kwargs),
        "phase": phase,
    }
    if runner_name:
        record["runner_name"] = runner_name
    if runner_kwargs:
        record["runner_kwargs"] = dict(runner_kwargs)

    _ENQUEUED.append(record)
    return record


def get_service_status(*, service_path: str, phase: str) -> dict[str, Any]:
    return {
        "status": "queued",
        "service_path": service_path,
        "phase": phase,
    }


__all__ = ["enqueue_service", "get_service_status"]
