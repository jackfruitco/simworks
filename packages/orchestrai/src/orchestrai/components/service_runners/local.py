"""In-process service runner."""

from __future__ import annotations

import inspect
from typing import Any

from asgiref.sync import async_to_sync

from .base import register_service_runner


class LocalServiceRunner:
    """Execute services immediately in the current process."""

    name = "local"

    def _build_service(self, service_cls, service_kwargs: dict[str, Any]):
        return service_cls(**service_kwargs)

    def start(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        service = self._build_service(service_cls, service_kwargs)
        kwargs = dict(runner_kwargs or {})
        if inspect.iscoroutinefunction(getattr(service, "aexecute", None)):
            return async_to_sync(service.aexecute)(**kwargs)
        if callable(getattr(service, "execute", None)):
            return service.execute(**kwargs)
        raise AttributeError(f"Service {service_cls} does not expose execute/aexecute")

    def enqueue(self, **payload: Any):
        return self.start(**payload)

    def stream(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        service = self._build_service(service_cls, service_kwargs)
        kwargs = dict(runner_kwargs or {})
        if inspect.iscoroutinefunction(getattr(service, "run_stream", None)):
            return async_to_sync(service.run_stream)(**kwargs)
        if callable(getattr(service, "run_stream", None)):
            return service.run_stream(**kwargs)
        raise AttributeError(f"Service {service_cls} does not support streaming")

    def get_status(self, **_: Any):
        raise NotImplementedError("Local runner does not track background status")


register_service_runner(
    LocalServiceRunner.name, LocalServiceRunner, make_default=True, allow_override=False
)


__all__ = ["LocalServiceRunner"]
