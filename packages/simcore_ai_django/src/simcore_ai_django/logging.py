# simcore_ai_django/logging.py
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from collections.abc import Mapping, MutableMapping
from typing import Any, Dict, Iterator, AsyncIterator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_TRACER: Tracer | None = None


def get_tracer() -> Tracer:
    """Return a module-level tracer for simcore_ai_django.

    The global OTEL SDK should be configured by your app (e.g., logfire.init or OTLP exporter).
    """
    global _TRACER
    if _TRACER is None:
        _TRACER = trace.get_tracer("simcore_ai_django")
    return _TRACER


def _span_attributes_from_ctx(ctx: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not ctx:
        return {}
    # Whitelist common attributes to avoid leaking large objects
    keys = (
        "namespace",
        "namespace",
        "kind",
        "service_name",
        "provider_name",
        "client_name",
        "object_db_pk",
        "correlation_id",
        "model",
        "stream",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        v = ctx.get(k)
        if v is not None:
            out[f"simcore.{k}"] = str(v)
    return out


@contextmanager
def service_span(name: str, *, attributes: Mapping[str, Any] | None = None) -> Iterator[None]:
    """Create a root/parent span for a full AI service run (sync).

    Example:
        with service_span("simcore.run_service", attributes={"simcore.namespace": ns, ...}):
            ...
    """
    tracer = get_tracer()
    attrs = dict(attributes or {})
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield
        except Exception as e:  # ensure failure reflected in span status
            span.set_status(Status(StatusCode.ERROR, description=str(e)))
            span.record_exception(e)
            raise


@asynccontextmanager
async def aservice_span(name: str, *, attributes: Mapping[str, Any] | None = None) -> AsyncIterator[None]:
    """Async variant of service_span."""
    tracer = get_tracer()
    attrs = dict(attributes or {})
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield
        except Exception as e:  # ensure failure reflected in span status
            span.set_status(Status(StatusCode.ERROR, description=str(e)))
            span.record_exception(e)
            raise


def inject_trace_headers(headers: MutableMapping[str, str] | None = None) -> MutableMapping[str, str]:
    """Inject current trace context into HTTP headers (for provider SDKs/HTTPX).

    Returns the mapping passed in (or a new one) with W3C traceparent/tracestate.
    """
    carrier: MutableMapping[str, str] = headers if headers is not None else {}
    TraceContextTextMapPropagator().inject(carrier)  # type: ignore[arg-type]
    return carrier


def current_traceparent() -> str | None:
    """Return the W3C traceparent string for the current span context, if any."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)  # populates traceparent/tracestate
    return carrier.get("traceparent")
