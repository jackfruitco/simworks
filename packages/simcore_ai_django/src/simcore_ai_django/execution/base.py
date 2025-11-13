# simcore_ai_django/execution/types.py
from __future__ import annotations
"""
Execution backend contract.

Backends are responsible for *how* a service is run:
  - `execute(...)` runs the service *synchronously* in-process and returns the service's return value.
  - `enqueue(...)` schedules the service *asynchronously* out-of-process and returns a task id `str`.

This sits behind the execution façade (e.g., `dispatch.execute`, `dispatch.enqueue`) and ahead of the service instance
(which actually instantiates the service and invokes its async entrypoint, e.g. `arun` or a streaming variant).

Tracing:
  Concrete backends should wrap both operations with spans:
    - `exec.backend.execute`
    - `exec.backend.enqueue`
  and include attributes such as:
    - `simcore.identity.service`  (namespace.kind.name, if available in kwargs)
    - `simcore.identity.codec`    (response/request codec identity, if available in kwargs)
    - correlation ids where present

  Backends should use the protected helper `_span_attrs_from_kwargs` instead of duplicating logic.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Optional, Protocol, runtime_checkable, Dict


@runtime_checkable
class SupportsServiceInit(Protocol):
    """A minimal constructor protocol for services executed by backends.

    Backends are expected to construct services as `service_cls(**kwargs)` using the kwargs passed to
    `BaseExecutionBackend.execute` / `BaseExecutionBackend.enqueue`.
    """
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

    This sits behind the execution façade (e.g., `dispatch.execute`, `dispatch.enqueue`) and ahead of the service
    instance (which is constructed and then has its async entrypoint, such as `arun` or a streaming variant,
    invoked by the backend or a thin runner).
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
        Extract common tracing attributes from kwargs using the standard simcore trace key names.
        Subclasses should call this helper instead of duplicating identity/correlation-id extraction.
        """
        ns = kwargs.get("namespace")
        kind = kwargs.get("kind") or kwargs.get("service_bucket")
        name = kwargs.get("name") or kwargs.get("service_name")
        codec_id = kwargs.get("codec")
        corr = kwargs.get("correlation_id") or kwargs.get("req_correlation_id") or kwargs.get("request_correlation_id")
        attrs: Dict[str, Any] = {}
        if ns or kind or name:
            attrs["simcore.identity.service"] = ".".join(x for x in (ns, kind, name) if x)
        if codec_id:
            attrs["simcore.identity.codec"] = codec_id
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
        Default passthrough for kwargs.
        Transport backends (e.g. Celery) should override this to coerce the mapping into a transport-
        safe shape (e.g. plain dict, JSON-serializable values). Callers should treat the returned
        mapping as the canonical version to send to the transport and not rely on the original
        object being preserved.
        """
        return kwargs