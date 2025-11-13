# packages/simcore_ai_django/src/simcore_ai_django/execution/backends/immediate.py
"""Immediate backend executes services synchronously and inline."""

from typing import Any, Dict, Optional, Type

from simcore_ai.tracing import service_span_sync
from simcore_ai.tracing.helpers import flatten_context as flatten_context_attrs
from simcore_ai_django.execution.base import BaseExecutionBackend, SupportsServiceInit
from simcore_ai_django.execution.dispatch import dispatch
from ..decorators import task_backend
from ...components import DjangoExecutableLLMService

BACKEND_NAME = "immediate"


@task_backend(BACKEND_NAME)
class ImmediateBackend(BaseExecutionBackend):
    supports_priority: bool = False

    def execute(self, *, service_cls: Type[DjangoExecutableLLMService], kwargs: Dict[str, Any]) -> Any:
        with service_span_sync(
                "exec.backend.execute",
                attributes={
                    "backend": BACKEND_NAME,
                    "service_cls": f"{service_cls.__module__}.{service_cls.__name__}",
                    **self._span_attrs_from_kwargs(kwargs),
                    **flatten_context_attrs(kwargs.get("context", {})),
                },
        ):
            svc: DjangoExecutableLLMService = service_cls(**kwargs)
            ctx_ = kwargs.get("context") or {}
            return svc.execute(context=ctx_)

    def enqueue(
            self,
            *,
            service_cls: Type[DjangoExecutableLLMService],
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
                    **flatten_context_attrs(kwargs.get("context", {})),
                },
        ):
            # Fallback: run inline but still return a synthetic id
            svc = service_cls(**kwargs)
            dispatch(
                service=svc,
                object_db_pk=kwargs.get("object_db_pk"),
                context=kwargs.get("context"),
            )
            return BACKEND_NAME
