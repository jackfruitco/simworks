# simcore_ai_django/execution/django_tasks_backend.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Type

from simcore_ai.tracing import inject_trace, extract_trace, service_span_sync
from ..base import BaseExecutionBackend, SupportsServiceInit
from ..decorators import task_backend

BACKEND_NAME = "django_tasks"


@task_backend(BACKEND_NAME)
class DjangoTasksBackend(BaseExecutionBackend):
    """
    Placeholder backend for Django 6.0 Tasks.

    This backend is **not implemented yet**. It exists to reserve the
    canonical backend name ("django_tasks") and to provide tracing scaffolding
    so traces will nest correctly once implemented.

    Initialization raises `NotImplementedError` to avoid accidental use until
    the real integration is built.

    Conventions preserved here match the other backends:
    - Span names: `exec.backend.execute` / `exec.backend.enqueue`
    - Attributes: `backend`, fully qualified `service_cls`, queue/delay, and
      identity/correlation fields via `_span_attrs_from_kwargs`.
    - Priority: Django Tasks are expected to support priority; advertise this
      via `supports_priority = True` (the entrypoint will pass it when ready).
    """

    # Django Tasks will support priority; advertise for the entrypoint.
    supports_priority: bool = True

    def __init__(self) -> None:
        raise NotImplementedError(
            "DjangoTasksBackend is not implemented yet. Set AI_EXECUTION_BACKENDS['DEFAULT_BACKEND'] to 'immediate' or 'celery'."
        )

    def execute(self, *, service_cls: Type[SupportsServiceInit], kwargs: Mapping[str, Any]) -> Any:  # pragma: no cover - scaffold
        with service_span_sync(
            "exec.backend.execute",
            attributes={
                "backend": BACKEND_NAME,
                "service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                **self._span_attrs_from_kwargs(kwargs),
            },
        ):
            # Unreachable because __init__ raises
            raise NotImplementedError("DjangoTasksBackend.execute is not implemented yet")

    def enqueue(
        self,
        *,
        service_cls: Type[SupportsServiceInit],
        kwargs: Mapping[str, Any],
        delay_s: Optional[float] = None,
        queue: Optional[str] = None,
    ) -> str:  # pragma: no cover - scaffold
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
            # Prepare for future trace propagation (will attach to the task payload)
            try:
                traceparent = inject_trace()
            except Exception:
                traceparent = None

            # Unreachable because __init__ raises
            raise NotImplementedError("DjangoTasksBackend.enqueue is not implemented yet")

    # --- Future worker-side helper (example) -------------------------------------
    @staticmethod
    def _continue_trace(traceparent: Optional[str]):  # pragma: no cover - scaffold
        """Example extractor to be used inside the eventual task runner."""
        if not traceparent:
            return None
        try:
            return extract_trace(traceparent)
        except Exception:
            return None
