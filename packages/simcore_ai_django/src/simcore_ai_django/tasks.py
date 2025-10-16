from __future__ import annotations
from celery import shared_task
from importlib import import_module
from .runner import run_service  # NOTE: runner.py

def _import_service(service_path: str):
    mod, name = service_path.rsplit(":", 1)
    return getattr(import_module(mod), name)

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=5,           # seconds, exponential
    retry_backoff_max=600,     # cap 10m
    max_retries=5,
)
def run_service_task(self, *, service_path: str, service_kwargs: dict):
    """Celery task to run a service.

    The runner continues the trace via `traceparent` if provided in service_kwargs.
    """
    traceparent = service_kwargs.pop("traceparent", None)
    Service = _import_service(service_path)
    svc = Service(**service_kwargs)
    return run_service(service=svc, traceparent=traceparent)