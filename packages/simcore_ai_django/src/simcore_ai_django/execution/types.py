# simcore_ai_django/execution/types.py
from __future__ import annotations

"""
Execution backend contract.

Backends are responsible for *how* a service is run:
  - `execute(...)` runs the service *synchronously* in-process and returns the service's return value.
  - `enqueue(...)` schedules the service *asynchronously* out-of-process and returns a task id `str`.

This sits behind the executor façade (e.g., `execute_service`, `enqueue_service`) and ahead of the runner
(which actually invokes the service's `run`/`handle` logic). Concrete backends (Inline, Celery, future
Django Tasks) implement this ABC.

Tracing:
  Concrete backends should wrap both operations with spans:
    - `exec.backend.execute`
    - `exec.backend.enqueue`
  and include attributes such as:
    - `backend`, `service_cls`, `queue`, `delay_s`
    - `ai.identity.service`  (namespace.bucket.name, if available in kwargs)
    - `ai.identity.codec`    (response/request codec identity, if available in kwargs)
    - correlation ids where present

  Backends should use the protected helper `_span_attrs_from_kwargs` instead of duplicating logic.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Optional, Protocol, runtime_checkable, Dict


@runtime_checkable
class SupportsServiceInit(Protocol):
    """A minimal constructor protocol for services executed by backends."""
    def __init__(self, **kwargs: Any) -> None: ...


class BaseExecutionBackend(ABC):
    """
    Abstract base for execution backends.

    Implementations:
      - ImmediateBackend: executes immediately in-process
      - CeleryBackend: enqueues to Celery for async execution
      - (future) DjangoTasksBackend: enqueues to Django's tasks

    Notes:
      - `execute` MUST block and return the service's actual return value.
      - `enqueue` MUST NOT block and MUST return a transport-specific task id (string).
      - Backends may inject/propagate tracing contexts; the runner should extract/continue them.
    """

    # ---------- Public API ----------
    @abstractmethod
    def execute(self, *, service_cls: type[SupportsServiceInit], kwargs: Mapping[str, Any]) -> Any:
        """Run the service synchronously and return the service's return value."""
        ...

    @abstractmethod
    def enqueue(
        self,
        *,
        service_cls: type[SupportsServiceInit],
        kwargs: Mapping[str, Any],
        delay_s: Optional[float] = None,
        queue: Optional[str] = None,
    ) -> str:
        """Schedule the service asynchronously and return a task id string."""
        ...

    # ---------- Protected helpers (optional overrides) ----------
    def _span_attrs_from_kwargs(self, kwargs: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Extract common tracing attributes from kwargs.
        Subclasses should call this helper instead of duplicating logic.
        """
        ns = kwargs.get("namespace")
        bucket = kwargs.get("bucket") or kwargs.get("service_bucket")
        name = kwargs.get("name") or kwargs.get("service_name")
        codec_id = kwargs.get("codec_identity")
        corr = kwargs.get("correlation_id") or kwargs.get("req_correlation_id") or kwargs.get("request_correlation_id")
        attrs: Dict[str, Any] = {}
        if ns or bucket or name:
            attrs["ai.identity.service"] = ".".join(x for x in (ns, bucket, name) if x)
        if codec_id:
            attrs["ai.identity.codec"] = codec_id
        if corr:
            attrs["req.correlation_id"] = corr
        return attrs

    def _coerce_delay(self, delay_s: Optional[float]) -> Optional[float]:
        """Normalize delay values; negative/zero treated as None (execute ASAP)."""
        if delay_s is None:
            return None
        try:
            val = float(delay_s)
        except Exception:
            return None
        return val if val > 0 else None

    def _prepare_kwargs_for_transport(self, kwargs: Mapping[str, Any]) -> Mapping[str, Any]:
        """
        Default passthrough for kwargs; transport backends (e.g. Celery) should override to ensure
        all kwargs are safely serializable for the transport.
        """
        return kwargs