# simcore_ai_django/execution/entrypoint.py
from __future__ import annotations

"""
Single public entrypoint for executing services (sync or async) with optional per-call overrides.

Usage patterns
--------------
# Immediate execution using service + settings defaults
execute(MyService, user_id=123)
MyService.execute(user_id=123)

# Builder-style overrides (recommended)
MyService.using(backend="celery", run_after=60, priority=50).enqueue(user_id=123)
execute(MyService, using={"backend": "celery", "run_after": 60}).execute(user_id=123)

Resolution order
----------------
1) Explicit call intent: passing `enqueue=True` (or calling `.enqueue()`) forces async
2) Service rule: `require_enqueue=True` forces async (logs/trace an override if sync requested)
3) Service defaults: `execution_mode`, `execution_backend`, `execution_priority`, `execution_run_after`
4) Django settings: `AI_EXECUTION_BACKENDS = {"DEFAULT_MODE","DEFAULT_BACKEND","CELERY": {"queue_default": ...}}`
5) Hard defaults: mode='sync', backend='immediate', priority=0, run_after=0

Notes
-----
- Public API is a *single function* `execute(...)`. It decides whether to run inline or enqueue.
- Private helpers `_execute_now(...)` and `_enqueue(...)` perform the actual backend calls.
- Terminology uses Django Tasks style (queue_name, run_after, priority); we map to backend args.

Scope & non-goals
-----------------
This entrypoint ONLY decides *how* a service runs (sync vs async) and *which* backend to use.
It does **not**:
- resolve identities (namespace.kind.name) — handled in services/resolvers and the runner,
- build LLM requests — handled by `BaseLLMService.build_request(...)`,
- resolve or execute codecs — handled in the Django runner (`simcore_ai_django.runner`) and codec layer.
Backends perform scheduling/dispatch; the runner orchestrates request promotion/demotion, provider
calls, audits, and codec handling.
"""

from collections.abc import Mapping
from typing import Any, Optional, Dict, Union, Type
from datetime import datetime

from simcore_ai.tracing import service_span_sync

# Backend types / ABC
from .types import BaseExecutionBackend, SupportsServiceInit

from .helpers import (
    settings_default_backend,
    settings_default_mode,
    settings_default_queue_name,
    span_attrs_from_ctx,
)
from .registry import get_backend_by_name

from .backends.immediate import ImmediateBackend  # for type mapping only

try:
    from .backends.celery import CeleryBackend  # type: ignore
except Exception:  # pragma: no cover
    CeleryBackend = None  # type: ignore


# -------------------- Option resolution --------------------

def _normalize_run_after(value: Optional[Union[float, int, datetime]]) -> Optional[float]:
    """
    Normalize run_after to seconds (float).
    Accepts None, seconds (float/int), or absolute datetime (UTC-naive or aware).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, datetime):
        now = datetime.utcnow()
        delta = (value - now).total_seconds()
        return delta if delta > 0 else None
    return None


def _normalize_priority(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        iv = int(value)
    except Exception:
        return None
    if iv < -100:
        return -100
    if iv > 100:
        return 100
    return iv


def _resolve_mode(
        *,
        enqueue: Optional[bool],
        service_cls: Type[SupportsServiceInit],
) -> str:
    # 1) explicit call intent
    if enqueue is not None:
        return "async" if enqueue else "sync"
    # 2) service default
    svc_mode = getattr(service_cls, "execution_mode", None)
    if svc_mode in ("sync", "async"):
        return svc_mode
    # 3) settings default
    return settings_default_mode()


def _resolve_backend_name(
        *,
        backend: Optional[Union[str, Type[BaseExecutionBackend]]],
        service_cls: Type[SupportsServiceInit],
) -> str:
    if isinstance(backend, str):
        return backend.strip().lower()
    if isinstance(backend, type) and issubclass(backend, BaseExecutionBackend):
        # Allow passing the class directly
        name_map = {
            ImmediateBackend: "immediate",
            CeleryBackend: "celery",
        }
        return name_map.get(backend, settings_default_backend())
    # service default
    svc_backend = getattr(service_cls, "execution_backend", None)
    if isinstance(svc_backend, str):
        return svc_backend.strip().lower()
    # settings default
    return settings_default_backend()


def _resolve_queue_name(
        *,
        queue_name: Optional[str],
        backend_name: str,
) -> Optional[str]:
    if queue_name:
        return queue_name
    if backend_name == "celery":
        return settings_default_queue_name()
    return None


def _resolve_priority(
        *,
        priority: Optional[int],
        service_cls: Type[SupportsServiceInit],
) -> int:
    if priority is not None:
        return _normalize_priority(priority) or 0
    svc_prio = getattr(service_cls, "execution_priority", None)
    if svc_prio is not None:
        return _normalize_priority(svc_prio) or 0
    return 0


def _resolve_run_after(
        *,
        run_after: Optional[Union[float, int, datetime]],
        service_cls: Type[SupportsServiceInit],
) -> Optional[float]:
    if run_after is not None:
        return _normalize_run_after(run_after)
    svc_ra = getattr(service_cls, "execution_run_after", None)
    if svc_ra is not None:
        return _normalize_run_after(svc_ra)
    # settings default is effectively "now" for most backends
    return None


# -------------------- Private dispatchers --------------------

def _execute_now(
        *,
        backend: BaseExecutionBackend,
        service_cls: Type[SupportsServiceInit],
        ctx: Mapping[str, Any],
) -> Any:
    """
    Dispatch the service to the given backend for immediate (in-process) execution.

    Notes
    -----
    - This function does **not** instantiate the service or build requests.
      The backend is responsible for instantiation (via SupportsServiceInit) and for calling
      the Django runner which builds the request via `BaseLLMService.build_request(...)`.
    - No identity/codec resolution occurs here; that happens inside the runner/services.
    """
    attrs = {
        "backend": backend.__class__.__name__.lower(),
        "service_cls": getattr(service_cls, "__name__", str(service_cls)),
        **span_attrs_from_ctx(ctx),
    }
    attrs = {k: v for k, v in attrs.items() if v is not None}
    with service_span_sync("exec.entry.execute", attributes=attrs):
        return backend.execute(service_cls=service_cls, kwargs=ctx)


def _enqueue(
        *,
        backend: BaseExecutionBackend,
        service_cls: Type[SupportsServiceInit],
        ctx: Mapping[str, Any],
        queue_name: Optional[str],
        run_after_seconds: Optional[float],
        priority: Optional[int],
) -> str:
    """
    Enqueue the service for deferred execution using the selected backend.

    - Maps our canonical names to backend args: `queue_name` → `queue`, `run_after_seconds` → `delay_s`.
    - If a backend does not support `priority`, we mark `exec.priority.unsupported` in trace and ignore it.
    - Does not perform identity/request/codec logic — the runner handles that at execution time.
    """
    # Canonical → backend mapping
    queue = queue_name  # mapping
    delay_s = run_after_seconds  # mapping

    attrs = {
        "backend": backend.__class__.__name__.lower(),
        "service_cls": getattr(service_cls, "__name__", str(service_cls)),
        "queue_name": queue_name,
        "run_after": run_after_seconds,
        "priority": priority,
        **span_attrs_from_ctx(ctx),
    }
    attrs = {k: v for k, v in attrs.items() if v is not None}
    with service_span_sync("exec.entry.enqueue", attributes=attrs) as span:
        # Respect backend capabilities for priority; annotate trace when ignored.
        supports_priority = getattr(backend, "supports_priority", False)
        if not supports_priority and priority is not None:
            # mark unsupported in trace; ignore priority
            if span is not None:
                try:
                    span.set_attribute("exec.priority.unsupported", True)
                except Exception:
                    pass
            priority = None
        return backend.enqueue(service_cls=service_cls, kwargs=ctx, delay_s=delay_s, queue=queue)


# -------------------- Public API --------------------

def execute(
        service_cls: Type[SupportsServiceInit],
        *,
        using: Optional[Dict[str, Any]] = None,
        enqueue: Optional[bool] = None,
        backend: Optional[Union[str, Type[BaseExecutionBackend]]] = None,
        queue_name: Optional[str] = None,
        run_after: Optional[Union[float, int, datetime]] = None,
        priority: Optional[int] = None,
        **ctx: Any,
) -> Any | str:
    """
    Execute a service now (sync) or later (async) based on service defaults, settings, and overrides.

    - Pass `using={...}` to provide builder-style overrides (merged with explicit kwargs; explicit wins).
    - Pass `enqueue=True` to force async, or use the builder `.enqueue(...)` on the mixin.
    - Returns the service's return value (sync) or a task id string (async).

    This function is **transport-only**: it chooses mode/backend/queue and dispatches.
    Identity derivation, request construction, client/codec resolution, and audits happen later in
    the runner and service layers.
    """
    overrides = dict(using or {})
    if backend is not None:
        overrides["backend"] = backend
    if queue_name is not None:
        overrides["queue_name"] = queue_name
    if run_after is not None:
        overrides["run_after"] = run_after
    if priority is not None:
        overrides["priority"] = priority
    if enqueue is not None:
        overrides["enqueue"] = enqueue

    # Resolve mode/backend/options
    resolved_mode = _resolve_mode(enqueue=overrides.get("enqueue"), service_cls=service_cls)
    resolved_backend_name = _resolve_backend_name(backend=overrides.get("backend"), service_cls=service_cls)
    backend_inst = get_backend_by_name(resolved_backend_name)
    resolved_queue_name = _resolve_queue_name(queue_name=overrides.get("queue_name"),
                                              backend_name=resolved_backend_name)
    resolved_priority = _resolve_priority(priority=overrides.get("priority"), service_cls=service_cls)
    resolved_run_after = _resolve_run_after(run_after=overrides.get("run_after"), service_cls=service_cls)

    # Enforce service-level requirement
    if resolved_mode == "sync" and getattr(service_cls, "require_enqueue", False):
        _ov_attrs = {
            "reason": "service.require_enqueue",
            "from": "sync",
            "to": "async",
            "service_cls": getattr(service_cls, "__name__", str(service_cls)),
            **span_attrs_from_ctx(ctx),
        }
        _ov_attrs = {k: v for k, v in _ov_attrs.items() if v is not None}
        with service_span_sync("exec.entry.override", attributes=_ov_attrs):
            resolved_mode = "async"

    # Top-level trace
    _top_attrs = {
        "resolved.mode": resolved_mode,
        "resolved.backend": resolved_backend_name,
        "queue_name": resolved_queue_name,
        "run_after": resolved_run_after,
        "priority": resolved_priority,
        **span_attrs_from_ctx(ctx),
        "service_cls": getattr(service_cls, "__name__", str(service_cls)),
    }
    _top_attrs = {k: v for k, v in _top_attrs.items() if v is not None}
    with service_span_sync("exec.entry", attributes=_top_attrs):
        if resolved_mode == "async":
            return _enqueue(
                backend=backend_inst,
                service_cls=service_cls,
                ctx=ctx,
                queue_name=resolved_queue_name,
                run_after_seconds=resolved_run_after,
                priority=resolved_priority,
            )
        return _execute_now(backend=backend_inst, service_cls=service_cls, ctx=ctx)


# -------------------- Service mixin & builder --------------------

class _ExecutionCall:
    """Lightweight builder for per-call overrides; non-autostart.

    Provides a small fluent API mirroring the service mixin:
      - `.using(**overrides)` to stage backend/mode knobs (e.g., backend, run_after, priority),
      - `.execute(**ctx)` to force sync now,
      - `.enqueue(**ctx)` to force async,
      - `.run(**ctx)` to defer the decision to resolution rules.

    This builder does not instantiate the service or perform identity/codec work.
    """

    def __init__(self, service_cls: Type[SupportsServiceInit], overrides: Optional[Dict[str, Any]] = None):
        self._service_cls = service_cls
        self._overrides: Dict[str, Any] = dict(overrides or {})

    def using(self, **more: Any) -> "_ExecutionCall":
        self._overrides.update(more)
        return self

    def execute(self, **ctx: Any) -> Any:
        """Force synchronous execution with current overrides.

        Transport-only: defers service instantiation and request building to the backend/runner.
        """
        ov = dict(self._overrides)
        ov["enqueue"] = False
        return execute(self._service_cls, using=ov, **ctx)

    def enqueue(self, **ctx: Any) -> str:
        """Force asynchronous execution with current overrides.

        Transport-only: enqueues with resolved backend and defers work to the runner at execution time.
        """
        ov = dict(self._overrides)
        ov["enqueue"] = True
        return execute(self._service_cls, using=ov, **ctx)  # type: ignore[return-value]

    def run(self, **ctx: Any) -> Any | str:
        """Resolve mode from overrides/service/settings and execute.

        Transport-only: no identity/request/codec logic here.
        """
        return execute(self._service_cls, using=self._overrides, **ctx)
