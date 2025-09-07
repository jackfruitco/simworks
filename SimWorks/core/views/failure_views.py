# core/views/failure_views.py
from django.shortcuts import render
from opentelemetry import trace


__all__ = ["csrf_failure"]


def csrf_failure(request, reason=""):
    trace_id = None
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        trace_id = f"{ctx.trace_id:032x}"
        span.set_attribute("django.csrf.reason", reason)

    return render(request, "403_csrf.html", {"reason": reason, "trace_id": trace_id}, status=403)
