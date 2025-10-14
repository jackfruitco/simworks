# simcore_ai_django/execution/celery_backend.py
from __future__ import annotations

from typing import Mapping, Any, Optional

from simcore_ai.tracing import inject_trace
from simcore_ai_django.execution.base_backend import BaseExecutionBackend
from simcore_ai_django.tasks import run_service_task


class CeleryBackend(BaseExecutionBackend):
    def execute(
            self,
            *,
            service_cls,
            kwargs: Mapping[str, Any]
    ) -> Any:
        from simcore_ai_django.runner import run_service
        svc = service_cls(**kwargs)
        return run_service(service=svc)

    def enqueue(
            self,
            *,
            service_cls,
            kwargs: Mapping[str, Any],
            delay_s: Optional[int] = None,
            queue: Optional[str] = None,
    ) -> str:
        eta = None
        if delay_s:
            from datetime import datetime, timedelta, timezone
            eta = datetime.now(timezone.utc) + timedelta(seconds=delay_s)

        # Inject current trace context so the worker continues the same trace
        traceparent = None
        try:
            traceparent = inject_trace()
        except Exception:
            traceparent = None

        task_kwargs = {
            "service_path": f"{service_cls.__module__}:{service_cls.__name__}",
            "service_kwargs": dict(kwargs),
        }
        if traceparent:
            task_kwargs["service_kwargs"]["traceparent"] = traceparent

        result = run_service_task.apply_async(
            kwargs=task_kwargs,
            queue=queue,
            eta=eta,
        )
        return result.id
