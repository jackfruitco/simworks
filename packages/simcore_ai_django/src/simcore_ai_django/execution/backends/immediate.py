# simcore_ai_django/execution/immediate.py
from simcore_ai_django.execution.base_backend import BaseExecutionBackend
from simcore_ai_django.runner import run_service

class ImmediateBackend(BaseExecutionBackend):
    def execute(self, *, service_cls, kwargs):
        svc = service_cls(**kwargs)
        return run_service(service=svc)

    def enqueue(self, *, service_cls, kwargs, delay_s=None, queue=None) -> str:
        # Fallback: run inline but still return a synthetic id
        svc = service_cls(**kwargs)
        run_service(service=svc)
        return "inline"