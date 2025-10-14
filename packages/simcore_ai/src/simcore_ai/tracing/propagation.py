# simcore_ai/tracing/propagation.py
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

def inject_trace() -> str | None:
    carrier: dict[str, str] = {}
    try:
        TraceContextTextMapPropagator().inject(carrier)
        return carrier.get("traceparent")
    except Exception:
        return None

def extract_trace(traceparent: str):
    try:
        return TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    except Exception:
        return None