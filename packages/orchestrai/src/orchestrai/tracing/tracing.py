"""Dependency-free tracing helpers.

These helpers intentionally avoid pulling in OpenTelemetry; they provide the
same call surface with lightweight no-op spans that collect attributes for
introspection in tests if needed.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Mapping

logger = logging.getLogger(__name__)


@dataclass
class Span:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def record_exception(self, err: BaseException) -> None:  # pragma: no cover - unused
        self.attributes.setdefault("exceptions", []).append(str(err))


@dataclass(frozen=True)
class SpanPath:
    parts: tuple[str, ...]

    def __str__(self) -> str:
        return ".".join(self.parts)

    @classmethod
    def from_str(cls, name: str) -> "SpanPath":
        name = (name or "").strip()
        return cls(tuple(p for p in name.split(".") if p)) if name else cls(())

    def child(self, *segments: str) -> "SpanPath":
        cleaned = tuple(s for s in segments if s)
        return SpanPath(self.parts + cleaned)


class _Tracer:
    def start_as_current_span(self, name: str, kind: object | None = None):  # pragma: no cover - compat
        @contextmanager
        def ctx():
            yield Span(name)

        return ctx()


def get_tracer(name: str | None = None):  # pragma: no cover - trivial
    return _Tracer()


def _apply_attributes(span: Span, attrs: Mapping[str, Any] | None) -> None:
    if not attrs:
        return
    try:
        span.attributes.update({k: v for k, v in attrs.items() if v is not None})
    except Exception:  # pragma: no cover - defensive
        logger.debug("trace.attr.set_failed", exc_info=True)


def _record_exception(span: Span, err: BaseException) -> None:
    try:
        span.record_exception(err)
    except Exception:  # pragma: no cover - defensive
        logger.debug("trace.record_exception_failed", exc_info=True)


@contextmanager
def service_span_sync(name: str | SpanPath, *, attributes: Mapping[str, Any] | None = None) -> Iterator[Span]:
    span_name = str(name) if isinstance(name, SpanPath) else name
    span = Span(span_name)
    _apply_attributes(span, attributes)
    try:
        yield span
        span.set_attribute("ok", True)
    except Exception as exc:
        span.set_attribute("ok", False)
        _record_exception(span, exc)
        raise


@asynccontextmanager
async def service_span(name: str | SpanPath, *, attributes: Mapping[str, Any] | None = None) -> AsyncIterator[Span]:
    with service_span_sync(name, attributes=attributes) as span:
        yield span


__all__ = ["SpanPath", "get_tracer", "service_span", "service_span_sync"]
