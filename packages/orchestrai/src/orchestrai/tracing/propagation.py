"""Tiny trace propagation helpers used in tests.

The original implementation depended on OpenTelemetry; the refactored version
keeps a minimal, dependency-free API that still matches call sites.
"""
from __future__ import annotations


def inject_trace() -> str | None:
    return None


def extract_trace(traceparent: str):  # pragma: no cover - placeholder
    return None


__all__ = ["inject_trace", "extract_trace"]
