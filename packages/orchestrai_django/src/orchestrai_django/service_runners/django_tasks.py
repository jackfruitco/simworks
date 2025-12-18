from __future__ import annotations

from typing import Any, Mapping

from asgiref.sync import async_to_sync, sync_to_async
from django.tasks.base import Task

from orchestrai.components.services.service import BaseService
from orchestrai.service_runners import BaseServiceRunner


class DjangoTaskRunner(BaseServiceRunner):
    """Service runner that dispatches OrchestrAI services via Django Tasks."""

    def __init__(self, service_tasks: Mapping[str, Task]) -> None:
        self.service_tasks: dict[str, Task] = dict(service_tasks)

    @staticmethod
    def default_runner_name(service_cls: type[BaseService]) -> str:
        """Return the default runner name for a service (identity-aware)."""

        identity = getattr(service_cls, "identity", None)
        label = getattr(identity, "as_str", None) or getattr(identity, "name", None)
        return str(label or getattr(service_cls, "__name__", "<unknown service>"))

    def _resolve_task(self, service_cls: type[BaseService]) -> tuple[str, Task]:
        runner_name = self.default_runner_name(service_cls)
        try:
            task = self.service_tasks[runner_name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise LookupError(f"No Django task is registered for runner '{runner_name}'") from exc
        return runner_name, task

    @staticmethod
    def _build_payload(
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "service_cls": service_cls,
            "service_kwargs": dict(service_kwargs),
            "phase": phase,
        }
        if runner_kwargs:
            payload["runner_kwargs"] = dict(runner_kwargs)
        return payload

    @staticmethod
    def _run_inline(task: Task | Any, payload: dict[str, Any]) -> Any:
        if hasattr(task, "call"):
            return task.call(**payload)
        if callable(task):
            return task(**payload)
        raise TypeError("Provided task is not callable")

    def start(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        runner_name, task = self._resolve_task(service_cls)
        payload = self._build_payload(
            service_cls=service_cls,
            service_kwargs=service_kwargs,
            phase=phase,
            runner_kwargs=runner_kwargs,
        )
        return self._run_inline(task, payload | {"runner_name": runner_name})

    def enqueue(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        runner_name, task = self._resolve_task(service_cls)
        payload = self._build_payload(
            service_cls=service_cls,
            service_kwargs=service_kwargs,
            phase=phase,
            runner_kwargs=runner_kwargs,
        )
        payload["runner_name"] = runner_name

        async def _enqueue() -> Any:
            if hasattr(task, "aenqueue"):
                return await task.aenqueue(**payload)
            if hasattr(task, "enqueue"):
                return await sync_to_async(task.enqueue)(**payload)
            return await sync_to_async(self._run_inline)(task, payload)

        return async_to_sync(_enqueue)()

    def stream(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        raise NotImplementedError("Streaming is not supported for Django task runners")

    def get_status(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        result = None
        if runner_kwargs:
            result = runner_kwargs.get("task_result") or runner_kwargs.get("result")
        refresher = getattr(result, "refresh", None)
        if callable(refresher):
            refresher()
        return result


__all__ = ["DjangoTaskRunner"]
