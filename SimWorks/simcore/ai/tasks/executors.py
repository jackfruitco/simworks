# simcore/ai/executors.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from typing import Any
from asgiref.sync import async_to_sync
from functools import partial

from celery import shared_task

logger = logging.getLogger(__name__)


def dotted_path(fn) -> str:
    return f"{fn.__module__}.{fn.__qualname__}"


def resolve(dotted: str):
    mod_name, attr = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


# -- Async helpers -------------------------------------------------------------

def _run_async(fn, *args, timeout: float | None = None, **kwargs):
    async def _runner():
        coro = fn(*args, **kwargs)
        if timeout:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro
    # Bridge safely even if an event loop is already running in the worker
    return async_to_sync(_runner)()


def _run_maybe_async(fn, *args, timeout: float | None = None, **kwargs):
    if inspect.iscoroutinefunction(fn):
        return _run_async(fn, *args, timeout=timeout, **kwargs)
    # Call sync function
    result = fn(*args, **kwargs)
    return result


@shared_task(
    name="ai.execute_connector",
    # queue="ai",
    bind=True,
    autoretry_for=(),
    retry_backoff=False
)
def execute_connector(self, connector_path: str, *args, **kwargs) -> Any:
    """
    Runs a connector (sync or async) and returns a JSON-serializable result.

    Args:
        connector_path: dotted path to the callable
        *args, **kwargs: forwarded to the callable
            Special kwarg: `_timeout` seconds (applies to async callables)

    Use .apply(...) for immediate, .apply_async(...) to enqueue.
    """
    logger.debug(f"executing connector '{connector_path}'...")

    fn = resolve(connector_path)
    timeout = kwargs.pop("_timeout", None)
    try:
        return _run_maybe_async(fn, *args, timeout=timeout, **kwargs)
    except Exception:
        logger.exception("connector '%simulation' failed", connector_path)
        raise
