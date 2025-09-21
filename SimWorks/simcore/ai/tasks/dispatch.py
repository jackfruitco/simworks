# simcore/ai/tasks/dispatch.py
from __future__ import annotations

import logging
from typing import Any

from celery.result import AsyncResult

from .executors import execute_connector, dotted_path

logger = logging.getLogger(__name__)


def call_connector(
        fn,
        *args,
        enqueue: bool = True,
        eta=None,
        countdown=None,
        **kwargs
) -> Any | AsyncResult:
    """Call connector and return result."""
    logger.debug(f"calling connector '{fn}' (enqueued={enqueue})...")

    path = dotted_path(fn)
    if enqueue:
        return execute_connector.apply_async((path, *args), kwargs, eta=eta, countdown=countdown)
    # Run synchronously in-process (returns final value, not AsyncResult)
    resp = execute_connector.apply((path, *args), kwargs)
    return resp.result
