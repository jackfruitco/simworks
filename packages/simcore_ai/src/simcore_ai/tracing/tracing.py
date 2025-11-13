from __future__ import annotations

import logging
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Iterator, AsyncIterator
from collections.abc import Mapping

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tracer utilities
# ---------------------------------------------------------------------------

_DEFAULT_TRACER_NAME = "simcore_ai"


def get_tracer(name: str | None = None) -> Tracer:
    """Return an OpenTelemetry tracer for this package.

    If a name isn't supplied, a package-level default is used so spans nest
    nicely regardless of call site.
    """
    return trace.get_tracer(name or _DEFAULT_TRACER_NAME)


def _apply_attributes(span: Span, attrs: Mapping[str, Any] | None) -> None:
    if not attrs:
        return
    # OpenTelemetry allows only: bool, str, bytes, int, float, or sequences of those.
    ALLOWED = (bool, str, bytes, int, float)
    for k, v in attrs.items():
        try:
            if v is None:
                # Skip Nones entirely to avoid warnings like
                # "Invalid type NoneType for attribute ..."
                continue
            # Accept plain scalars of allowed types
            if isinstance(v, ALLOWED):
                span.set_attribute(k, v)
                continue
            # Accept sequences of allowed scalars (but not str/bytes themselves)
            from collections.abc import Sequence
            if isinstance(v, Sequence) and not isinstance(v, (str, bytes)):
                cleaned = [x for x in v if isinstance(x, ALLOWED)]
                if cleaned:
                    span.set_attribute(k, cleaned)
                # If nothing valid remains, skip silently
                continue
            # Unsupported type: skip silently
            continue
        except Exception:
            # Defensive: never let tracing raise or log noisy errors here.
            # Use DEBUG so we can inspect locally without polluting prod logs.
            logger.debug("trace.attr.set_failed", extra={"key": k}, exc_info=True)


def _record_exception(span: Span, err: BaseException) -> None:
    try:
        span.record_exception(err)
        span.set_status(Status(StatusCode.ERROR, description=str(err)))
        span.set_attribute("exception.type", type(err).__name__)
        span.set_attribute("exception.msg", str(err)[:500])
    except Exception:  # defensive: never raise from tracing
        logger.exception("trace.record_exception_failed")


# ---------------------------------------------------------------------------
# Context managers for spans
# ---------------------------------------------------------------------------

@contextmanager
def service_span_sync(name: str, *, attributes: Mapping[str, Any] | None = None) -> Iterator[Span]:
    """Synchronous span context for service orchestration.

    Usage:
        with service_span_sync("simcore.compile_schema", attributes={"simcore.namespace": ns}):
            ...
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        _apply_attributes(span, attributes)
        try:
            yield span
            span.set_attribute("ok", True)
        except Exception as e:
            span.set_attribute("ok", False)
            _record_exception(span, e)
            raise


@asynccontextmanager
async def service_span(name: str, *, attributes: Mapping[str, Any] | None = None) -> AsyncIterator[Span]:
    """Async span context for service orchestration.

    Usage:
        async with service_span("simcore.provider.call", attributes={"simcore.provider": "openai"}):
            ...
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        _apply_attributes(span, attributes)
        try:
            yield span
            span.set_attribute("ok", True)
        except Exception as e:
            span.set_attribute("ok", False)
            _record_exception(span, e)
            raise


__all__ = [
    "get_tracer",
    "service_span",
    "service_span_sync",
]
