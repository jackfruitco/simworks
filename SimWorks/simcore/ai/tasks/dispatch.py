# simcore/ai/tasks/dispatch.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery.result import AsyncResult

from .executors import execute_connector, dotted_path

logger = logging.getLogger(__name__)


async def acall_connector(
        fn,
        *args,
        enqueue: bool = True,
        eta=None,
        countdown=None,
        **kwargs
) -> Any | AsyncResult:
    """Async connector dispatcher."""
    logger.debug(f"acall_connector: '{fn}' (enqueued={enqueue})...")
    path = dotted_path(fn)
    if enqueue:
        return execute_connector.apply_async(
            args=(path, *args),
            kwargs=kwargs,
            eta=eta,
            countdown=countdown
        )
    # Celery apply is sync; wrap in asyncio thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: execute_connector.apply(args=(path, *args), kwargs=kwargs).result
    )


def call_connector(
        fn,
        *args,
        enqueue: bool = True,
        eta=None,
        countdown=None,
        **kwargs
) -> Any | AsyncResult:
    from asgiref.sync import async_to_sync
    return async_to_sync(acall_connector)(fn, *args, enqueue=enqueue, eta=eta, countdown=countdown, **kwargs)
