"""Compatibility layer for service dispatch helpers."""

from orchestrai.components.services.calls import ServiceCall


def _coerce_runner_name(*_args, **_kwargs):  # pragma: no cover - compatibility
    raise ImportError("Service runners have been removed; inline task execution is required.")


__all__ = ["ServiceCall", "_coerce_runner_name"]
