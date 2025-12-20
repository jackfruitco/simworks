"""Django Tasks-backed runner."""

from __future__ import annotations

from typing import Any

from orchestrai.components.service_runners import LocalServiceRunner, register_service_runner
from orchestrai_django import tasks


class DjangoTaskServiceRunner:
    """Queue services through the Django Tasks layer."""

    name = "django"

    def __init__(self) -> None:
        self._local = LocalServiceRunner()

    def enqueue(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        payload = {
            "service_cls": service_cls,
            "service_kwargs": dict(service_kwargs),
            "phase": phase,
        }
        if runner_kwargs:
            payload["runner_kwargs"] = dict(runner_kwargs)
        return tasks.enqueue_service(**payload)

    def start(self, **payload: Any):
        return self._local.start(**payload)

    def stream(self, **payload: Any):
        return self._local.stream(**payload)

    def get_status(self, **payload: Any):
        return tasks.get_service_status(**payload)


register_service_runner(
    DjangoTaskServiceRunner.name,
    DjangoTaskServiceRunner,
    make_default=True,
    allow_override=True,
)


__all__ = ["DjangoTaskServiceRunner"]
