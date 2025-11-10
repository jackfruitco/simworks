# simcore_ai_django/execution/registry.py
from __future__ import annotations

"""
Backend registry & singleton factory for execution backends.

This module centralizes registration and lookup of execution backends. It supports
lazy autodiscovery of common backends ("immediate" and "celery") and caches
singleton instances per backend name.

Alias notes: callers may request "celery" or "celery_backend"; both resolve to
"celery". Likewise, "inline" maps to "immediate".

Design:
- Registry stores backend CLASSES keyed by normalized name.
- Singletons cache INSTANCES keyed by the same name.
- Names are normalized to lowercase and mapped through `_NAME_ALIASES`.
- No identity logic lives here; it is purely backend keyed.
"""

from threading import RLock
from typing import Dict, Optional, Type

from .types import BaseExecutionBackend

# -------------------- name normalization / aliases --------------------
_NAME_ALIASES = {
    "celery_backend": "celery",
    "inline": "immediate",
}


def _normalize_name(name: str | None) -> str:
    key = (name or "immediate").strip().lower()
    return _NAME_ALIASES.get(key, key)


__all__ = [
    "register_backend",
    "get_backend_instance",
    "require_backend_instance",
    "get_backend_class",
    "require_backend_class",
    "list_backends",
    "list_backend_names",
]

# Registered backend classes by normalized name
_BACKEND_REGISTRY: Dict[str, Type[BaseExecutionBackend]] = {}
# Singleton instances by normalized name
_BACKEND_SINGLETONS: Dict[str, BaseExecutionBackend] = {}
# Guard for concurrent registration/creation
_LOCK = RLock()


# -------------------- registration API --------------------

def register_backend(name: str, backend_cls: Type[BaseExecutionBackend]) -> None:
    """Register a backend class under a normalized name.

    Example:
        register_backend("immediate", ImmediateBackend)
        register_backend("celery", CeleryBackend)
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("backend name must be a non-empty string")
    if not isinstance(backend_cls, type):  # duck-typed; Protocol/ABC tolerated
        raise TypeError("backend_cls must be a class")

    key = _normalize_name(name)
    with _LOCK:
        _BACKEND_REGISTRY[key] = backend_cls
        # do not eagerly overwrite an existing singleton; next lookup decides


# -------------------- lookup (classes) --------------------

def get_backend_class(name: str | None) -> Optional[Type[BaseExecutionBackend]]:
    key = _normalize_name(name or "")
    with _LOCK:
        cls = _BACKEND_REGISTRY.get(key)
        if cls is not None:
            return cls

    # attempt lazy discovery on first miss
    _lazy_discover_common_backends()
    with _LOCK:
        return _BACKEND_REGISTRY.get(key)


def require_backend_class(name: str | None) -> Type[BaseExecutionBackend]:
    cls = get_backend_class(name)
    if cls is None:
        # Fallback to immediate (try to ensure it's present)
        _ensure_immediate_registered()
        cls = _BACKEND_REGISTRY.get("immediate")
    if cls is None:
        raise RuntimeError("No execution backend available (missing 'immediate')")
    return cls


# -------------------- lookup (instances / singletons) --------------------

def get_backend_instance(name: str | None) -> BaseExecutionBackend:
    key = _normalize_name(name or "")
    with _LOCK:
        inst = _BACKEND_SINGLETONS.get(key)
        if inst is not None:
            return inst

    cls = get_backend_class(key)
    if cls is None:
        # fallback to immediate
        cls = require_backend_class("immediate")
        key = "immediate"

    # create instance outside initial lock to avoid long critical section
    instance = cls()  # type: ignore[call-arg]
    with _LOCK:
        # publish or return the existing one if a race created it
        existing = _BACKEND_SINGLETONS.get(key)
        if existing is not None:
            return existing
        _BACKEND_SINGLETONS[key] = instance
        return instance


def require_backend_instance(name: str | None) -> BaseExecutionBackend:
    return get_backend_instance(name)


def list_backends() -> Dict[str, str]:
    """Return a snapshot mapping of name -> class __name__ for diagnostics."""
    with _LOCK:
        return {k: v.__name__ for k, v in _BACKEND_REGISTRY.items()}

def list_backend_names() -> list[str]:
    """Return list of names of all registered backends (normalized)."""
    with _LOCK:
        return list(_BACKEND_REGISTRY.keys())


# -------------------- lazy discovery helpers --------------------

def _ensure_immediate_registered() -> None:
    with _LOCK:
        if "immediate" in _BACKEND_REGISTRY:
            return
    try:
        from .backends.immediate import ImmediateBackend  # noqa: F401
        register_backend("immediate", ImmediateBackend)
    except Exception:
        # Swallow import errors; caller will raise if still missing
        pass


def _lazy_discover_common_backends() -> None:
    # Best-effort discovery; keep imports guarded so projects without Celery don't crash
    _ensure_immediate_registered()
    try:
        from .backends.celery_backend import CeleryBackend  # noqa: F401
        register_backend("celery", CeleryBackend)
    except Exception:
        pass


# -------------------- eager best-effort registration --------------------
# Do this at import time but keep fully guarded.
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
