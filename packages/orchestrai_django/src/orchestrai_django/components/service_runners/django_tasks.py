# orchestrai_django/components/service_runners/django_tasks.py
"""Django Tasks-backed runner."""


from typing import Any

from orchestrai.components.services.runners import LocalServiceRunner, register_service_runner
from orchestrai_django import tasks


class DjangoTaskServiceRunner:
    """Queue services through the Django Tasks layer."""

    name = "django"

    def __init__(self) -> None:
        self._local = LocalServiceRunner()

    def enqueue(
        self,
        *,
        service_cls: type[Any],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        service_path = f"{service_cls.__module__}:{service_cls.__qualname__}"
        payload: dict[str, Any] = {
            "service_path": service_path,
            "service_kwargs": dict(service_kwargs),
            "phase": phase,
            "runner_name": self.name,
        }
        if runner_kwargs:
            payload["runner_kwargs"] = dict(runner_kwargs)
        return tasks.enqueue_service(**payload)

    def start(self, **payload: Any) -> Any:
        return self._local.start(**payload)

    def stream(self, **payload: Any) -> Any:
        return self._local.stream(**payload)

    def get_status(
        self,
        *,
        service_cls: type[Any],
        phase: str,
    ) -> Any:
        service_path = f"{service_cls.__module__}:{service_cls.__qualname__}"
        return tasks.get_service_status(service_path=service_path, phase=phase)


register_service_runner(
    DjangoTaskServiceRunner.name,
    DjangoTaskServiceRunner,
    make_default=True,
    allow_override=True,
)

__all__ = ["DjangoTaskServiceRunner"]
