from __future__ import annotations
from typing import Any, Optional
from .execution import get_backend

def execute_service(service_cls, **kwargs) -> Any:
    """Run immediately in-process and return the service result."""
    return get_backend().execute(service_cls=service_cls, kwargs=kwargs)

def enqueue_service(
    service_cls,
    *,
    delay_s: Optional[int] = None,
    queue: Optional[str] = None,
    **kwargs,
) -> str:
    """Enqueue for deferred execution; returns task id (or 'inline')."""
    return get_backend().enqueue(
        service_cls=service_cls,
        kwargs=kwargs,
        delay_s=delay_s,
        queue=queue,
    )