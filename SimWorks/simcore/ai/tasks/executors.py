# simcore/ai/executors.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


def dotted_path(fn) -> str:
    return f"{fn.__module__}.{fn.__qualname__}"


def resolve(dotted: str):
    mod_name, attr = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


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
    Use .apply(...) for immediate, .apply_async(...) to enqueue.
    """
    logger.debug(f"executing connector '{connector_path}'...")

    fn = resolve(connector_path)
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(*args, **kwargs))
    return fn(*args, **kwargs)
