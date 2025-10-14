from __future__ import annotations
from django.conf import settings
from .base_backend import BaseExecutionBackend

def get_backend() -> BaseExecutionBackend:
    backend = getattr(settings, "AI_EXECUTION_BACKEND", "immediate")
    if backend == "celery":
        from .backends import CeleryBackend
        return CeleryBackend()
    if backend in {"django_tasks", "django", "tasks"}:
        from .backends import DjangoTasksBackend
        return DjangoTasksBackend()  # will raise NotImplementedError for now
    from .backends import ImmediateBackend
    return ImmediateBackend()