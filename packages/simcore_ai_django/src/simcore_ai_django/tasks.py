from __future__ import annotations
from celery import shared_task
from importlib import import_module
from .runner import run_service  # NOTE: runner.py

def _import_service(service_path: str):
    mod, name = service_path.split(":")
    return getattr(import_module(mod), name)

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=5,           # seconds, exponential
    retry_backoff_max=600,     # cap 10m
    max_retries=5,
)
def run_service_task(self, *, service_path: str, service_kwargs: dict):
    """Celery task to run a service"""
    # Extract trace context if present, then continue the trace while executing
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        from simcore_ai.tracing import get_tracer
        carrier = {"traceparent": service_kwargs.pop("traceparent", "")}
        ctx = TraceContextTextMapPropagator().extract(carrier)
        tracer = get_tracer("simcore_ai_django.celery")
    except Exception:
        ctx = None
        tracer = None

    Service = _import_service(service_path)
    svc = Service(**service_kwargs)

    if tracer is not None and ctx is not None:
        with tracer.start_as_current_span("ai.task.run_service", context=ctx):
            return run_service(service=svc)
    # Fallback if tracing init failed
    return run_service(service=svc)