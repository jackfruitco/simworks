"""In-process service runner."""

from __future__ import annotations

import inspect
import logging
from typing import Any

import asyncio

from asgiref.sync import async_to_sync, sync_to_async

from .base import register_service_runner


logger = logging.getLogger(__name__)


class LocalServiceRunner:
    """Execute services immediately in the current process."""

    name = "local"

    @staticmethod
    def _in_running_loop() -> bool:
        """Return True if called from a thread with a running asyncio event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    @staticmethod
    def _run_coro_from_sync(coro):
        """Run a coroutine from sync code.

        If we're already inside an event loop, we *cannot* block waiting for it
        without risking deadlocks. In that case, the caller must use `astart()`.
        """
        if LocalServiceRunner._in_running_loop():
            raise RuntimeError(
                "LocalServiceRunner.start() was called from an async context. "
                "Use `await runner.astart(...)` instead."
            )
        return asyncio.run(coro)

    def _build_service(self, service_cls, service_kwargs: dict[str, Any]):
        return service_cls(**service_kwargs)

    def start(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        service = self._build_service(service_cls, service_kwargs)
        kwargs = dict(runner_kwargs or {})

        aexecute = getattr(service, "aexecute", None)
        if inspect.iscoroutinefunction(aexecute):
            # Native sync execution of an async service.
            return self._run_coro_from_sync(aexecute(**kwargs))

        execute = getattr(service, "execute", None)
        if callable(execute):
            return execute(**kwargs)

        raise AttributeError(f"Service {service_cls} does not expose execute/aexecute")

    async def astart(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        """Async-native execution.

        - If the service provides `aexecute`, await it.
        - Otherwise run `execute` in a thread via sync_to_async.
        """
        service = self._build_service(service_cls, service_kwargs)
        kwargs = dict(runner_kwargs or {})

        aexecute = getattr(service, "aexecute", None)
        if inspect.iscoroutinefunction(aexecute):
            return await aexecute(**kwargs)

        execute = getattr(service, "execute", None)
        if callable(execute):
            return await sync_to_async(execute, thread_sensitive=True)(**kwargs)

        raise AttributeError(f"Service {service_cls} does not expose execute/aexecute")

    def enqueue(self, **payload: Any):
        logger.debug(f"{self.__class__.__name__} does not support `enqueue`; dispatching `start`")
        return self.start(**payload)

    async def aenqueue(self, **payload: Any):
        logger.debug(f"{self.__class__.__name__} does not support `aenqueue`; dispatching `astart`")
        return await self.astart(**payload)

    def stream(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        service = self._build_service(service_cls, service_kwargs)
        kwargs = dict(runner_kwargs or {})

        run_stream = getattr(service, "run_stream", None)
        if inspect.iscoroutinefunction(run_stream):
            return self._run_coro_from_sync(run_stream(**kwargs))

        if callable(run_stream):
            return run_stream(**kwargs)

        raise AttributeError(f"Service {service_cls} does not support streaming")

    async def astream(self, *, service_cls, service_kwargs: dict[str, Any], phase: str, runner_kwargs=None):
        service = self._build_service(service_cls, service_kwargs)
        kwargs = dict(runner_kwargs or {})

        run_stream = getattr(service, "run_stream", None)
        if inspect.iscoroutinefunction(run_stream):
            return await run_stream(**kwargs)

        if callable(run_stream):
            return await sync_to_async(run_stream, thread_sensitive=True)(**kwargs)

        raise AttributeError(f"Service {service_cls} does not support streaming")

    def get_status(self, **_: Any):
        raise NotImplementedError("Local runner does not track background status")


register_service_runner(
    LocalServiceRunner.name, LocalServiceRunner, make_default=True, allow_override=False
)


__all__ = ["LocalServiceRunner"]
