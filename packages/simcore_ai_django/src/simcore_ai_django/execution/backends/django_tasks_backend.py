# simcore_ai_django/execution/django_tasks_backend.py
from __future__ import annotations

from typing import Mapping, Any, Optional

from simcore_ai.tracing import (
    inject_trace,
    extract_trace,
    service_span_sync,
)
from simcore_ai_django.execution.base_backend import BaseExecutionBackend


class DjangoTasksBackend(BaseExecutionBackend):
    """
    Placeholder backend for Django 6.0 Tasks.

    Tracing scaffolding is present (so future implementation will nest correctly
    under the caller's trace), but the backend is intentionally **not usable** yet.

    Instantiating this class raises NotImplementedError to avoid accidental use
    until Django tasks integration is implemented.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "DjangoTasksBackend is not implemented yet. Set AI_EXECUTION_BACKEND to 'immediate' or 'celery'."
        )

    def execute(self, *, service_cls, kwargs: Mapping[str, Any]) -> Any:  # pragma: no cover - scaffold
        with service_span_sync(
                "ai.tasks.execute",
                attributes={
                    "ai.backend": "django_tasks",
                    "ai.service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                },
        ):
            # This code path is unreachable because __init__ raises.
            raise NotImplementedError("DjangoTasksBackend.execute is not implemented yet")

    def enqueue(
            self,
            *,
            service_cls,
            kwargs: Mapping[str, Any],
            delay_s: Optional[int] = None,
            queue: Optional[str] = None,
    ) -> str:  # pragma: no cover - scaffold
        with service_span_sync(
                "ai.tasks.enqueue",
                attributes={
                    "ai.backend": "django_tasks",
                    "ai.service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                    "ai.delay_s": delay_s if delay_s is not None else 0,
                    "ai.queue": queue or "",
                },
        ):
            # Prepare for future trace propagation (will attach to the task payload)
            try:
                traceparent = inject_trace()
            except Exception:
                traceparent = None

            # This code path is unreachable because __init__ raises.
            raise NotImplementedError("DjangoTasksBackend.enqueue is not implemented yet")

    # --- Future worker-side helper (example) -------------------------------------
    @staticmethod
    def _continue_trace(traceparent: str | None):  # pragma: no cover - scaffold
        """Example extractor to be used inside the eventual task runner."""
        if not traceparent:
            return None
        try:
            return extract_trace(traceparent)
        except Exception:
            return None
