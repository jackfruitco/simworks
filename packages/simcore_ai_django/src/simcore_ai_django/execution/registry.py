# simcore_ai_django/execution/registry.py
from __future__ import annotations

"""
Backend registry & singleton factory for execution backends.

This module centralizes registration and lookup of execution backends. It supports
lazy autodiscovery of common backends ("immediate" and "celery") and caches
singleton instances per backend name.

Alias notes: callers may request "celery" or "celery_backend"; both resolve to the same backend. Likewise, "inline" maps to "immediate".
"""

from typing import Dict, Type

from .types import BaseExecutionBackend

# Name normalization/aliases so callers can use friendly names
_NAME_ALIASES = {
    "celery_backend": "celery",
    "inline": "immediate",
}


def _normalize_name(name: str) -> str:
    key = (name or "immediate").strip().lower()
    return _NAME_ALIASES.get(key, key)


__all__ = [
    "register_backend",
    "get_backend_by_name",
]

# Registered backend classes by normalized name
_BACKEND_REGISTRY: Dict[str, Type[BaseExecutionBackend]] = {}
# Singleton instances by normalized name
_BACKEND_SINGLETONS: Dict[str, BaseExecutionBackend] = {}


def register_backend(name: str, backend_cls: Type[BaseExecutionBackend]) -> None:
    """Register a backend class under a simple, lowercase name.

    Example:
        register_backend("immediate", InlineBackend)
        register_backend("celery", CeleryBackend)
    """
    key = _normalize_name(name)
    _BACKEND_REGISTRY[key] = backend_cls


def get_backend_by_name(name: str) -> BaseExecutionBackend:
    """Return a singleton instance of the backend for the given name.

    Performs best-effort autodiscovery of common backends on first use.
    Falls back to the "immediate" backend if the requested backend is unknown.
    """
    key = _normalize_name(name)
    if key in _BACKEND_SINGLETONS:
        return _BACKEND_SINGLETONS[key]
    backend_cls = _BACKEND_REGISTRY.get(key)
    if backend_cls is None:
        # Attempt optional imports for common backends to populate registry lazily
        try:
            from .backends.immediate import ImmediateBackend  # noqa: F401
            register_backend("immediate", ImmediateBackend)
        except Exception:
            pass
        try:
            from .backends.celery_backend import CeleryBackend  # noqa: F401
            register_backend("celery", CeleryBackend)
        except Exception:
            pass
        backend_cls = _BACKEND_REGISTRY.get(key)
        if backend_cls is None:
            # Fallback to immediate if still unresolved
            backend_cls = _BACKEND_REGISTRY.get("immediate")
            if backend_cls is None:
                # Last resort: import immediate and register immediately
                from .backends.immediate import ImmediateBackend
                register_backend("immediate", ImmediateBackend)
                backend_cls = ImmediateBackend
    inst = backend_cls()  # type: ignore[call-arg]
    _BACKEND_SINGLETONS[key] = inst
    return inst


# Eagerly register common backends on import (best-effort)
try:
    from .backends.immediate import ImmediateBackend  # noqa: F401

    register_backend("immediate", ImmediateBackend)
except Exception:
    pass
try:
    from .backends.celery_backend import CeleryBackend  # noqa: F401

    register_backend("celery", CeleryBackend)
except Exception:
    pass
