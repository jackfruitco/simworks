# simcore_ai_django/execution/immediate.py
"""Immediate backend executes services synchronously and inline."""

from typing import Any, Dict, Optional, Type

from simcore_ai.tracing import service_span_sync
from simcore_ai_django.execution.types import BaseExecutionBackend, SupportsServiceInit
from simcore_ai_django.runner import run_service
from ..decorators import task_backend

BACKEND_NAME = "immediate"


@task_backend(BACKEND_NAME)
class ImmediateBackend(BaseExecutionBackend):
    supports_priority: bool = False

    def execute(self, *, service_cls: Type[SupportsServiceInit], kwargs: Dict[str, Any]) -> Any:
        with service_span_sync(
                "exec.backend.execute",
                attributes={
                    "backend": BACKEND_NAME,
                    "service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                    **self._span_attrs_from_kwargs(kwargs),
                },
        ):
            svc = service_cls(**kwargs)
            return run_service(service=svc)

    def enqueue(
            self,
            *,
            service_cls: Type[SupportsServiceInit],
            kwargs: Dict[str, Any],
            delay_s: Optional[float] = None,
            queue: Optional[str] = None,
    ) -> str:
        with service_span_sync(
                "exec.backend.enqueue",
                attributes={
                    "backend": BACKEND_NAME,
                    "service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                    "queue": queue,
                    "delay_s": delay_s,
                    **self._span_attrs_from_kwargs(kwargs),
                },
        ):
            # Fallback: run inline but still return a synthetic id
            svc = service_cls(**kwargs)
            run_service(service=svc)
            return BACKEND_NAME
