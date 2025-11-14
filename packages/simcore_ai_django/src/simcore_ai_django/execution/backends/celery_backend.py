# simcore_ai_django/execution/celery_backend.py
"""
Celery execution backend for simcore AI Django.

This backend executes services synchronously or enqueues them as Celery tasks.
It supports tracing propagation and normalizes service kwargs for serialization.
"""

from __future__ import annotations

import enum
import os
import uuid
from collections.abc import Mapping
from datetime import datetime, date
from typing import Any, Optional

from pydantic import BaseModel

from simcore_ai.tracing import inject_trace, service_span_sync
from simcore_ai.tracing.helpers import flatten_context as flatten_context_attrs
from simcore_ai_django.execution.base import BaseExecutionBackend, SupportsServiceInit
from simcore_ai_django.tasks import run_service_task
from ..decorators import task_backend

BACKEND_NAME = "celery"


@task_backend(BACKEND_NAME)
class CeleryBackend(BaseExecutionBackend):
    """Celery backend to execute or enqueue service tasks."""

    supports_priority: bool = False

    def execute(
            self,
            *,
            service_cls: type[SupportsServiceInit],
            kwargs: Mapping[str, Any]
    ) -> Any:
        """
        Execute the service synchronously.

        :param service_cls: Service class to execute.
        :param kwargs: Keyword arguments for the service.
        :return: Result of the service execution.
        """
        with service_span_sync(
                "exec.backend.execute",
                attributes={
                    "backend": BACKEND_NAME,
                    "service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                    **self._span_attrs_from_kwargs(kwargs),
                    **flatten_context_attrs(kwargs.get("context", {})),
                },
        ):
            from simcore_ai_django.runner import run_service
            svc = service_cls(**kwargs)
            return run_service(
                service=svc,
                object_db_pk=kwargs.get("object_db_pk"),
                context=kwargs.get("context"),
            )

    def enqueue(
            self,
            *,
            service_cls: type[SupportsServiceInit],
            kwargs: Mapping[str, Any],
            delay_s: Optional[float] = None,
            queue: Optional[str] = None,
    ) -> str:
        """
        Enqueue the service as a Celery task.

        :param service_cls: Service class to enqueue.
        :param kwargs: Keyword arguments for the service.
        :param delay_s: Optional delay in seconds before task execution.
        :param queue: Optional Celery queue name.
        :return: Celery task id.
        """
        with service_span_sync(
                "exec.backend.enqueue",
                attributes={
                    "backend": BACKEND_NAME,
                    "service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                    "queue": queue,
                    "delay_s": delay_s,
                    **self._span_attrs_from_kwargs(kwargs),
                    **flatten_context_attrs(kwargs.get("context", {})),
                },
        ):
            eta = None
            if delay_s is not None:
                delay_s = float(delay_s)
                from datetime import datetime, timedelta, timezone
                eta = datetime.now(timezone.utc) + timedelta(seconds=delay_s)

            # Inject current trace context so the worker continues the same trace
            traceparent = None
            try:
                traceparent = inject_trace()
            except Exception:
                traceparent = None

            if queue is None:
                env_q = os.environ.get("SIMCORE_AI_DJANGO_CELERY_QUEUE_DEFAULT")
                if env_q:
                    queue = env_q

            serialized_kwargs = self._serialize_kwargs(kwargs)

            task_kwargs = {
                "service_path": f"{service_cls.__module__}:{service_cls.__name__}",
                "service_kwargs": dict(serialized_kwargs),
            }
            if traceparent:
                task_kwargs["service_kwargs"]["traceparent"] = traceparent

            result = run_service_task.apply_async(
                kwargs=task_kwargs,
                queue=queue,
                eta=eta,
            )
            return result.id

    @staticmethod
    def _serialize_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
        """
        Normalize kwargs for serialization:
        - Pydantic models converted via .model_dump()
        - Enums converted to their value
        - UUIDs converted to strings
        - datetime and date converted to ISO format string
        - Others left as is
        """

        def serialize_value(v: Any) -> Any:
            if isinstance(v, BaseModel):
                return v.model_dump()
            if isinstance(v, enum.Enum):
                return v.value
            if isinstance(v, uuid.UUID):
                return str(v)
            if isinstance(v, (datetime, date)):
                return v.isoformat()
            return v

        return {k: serialize_value(v) for k, v in kwargs.items()}
