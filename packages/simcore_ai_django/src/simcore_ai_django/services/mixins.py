# simcore_ai_django/services/mixins.py
from __future__ import annotations

"""
Execution conveniences for Django services.

This module exposes a mixin that gives any Django LLM service a
clean, Django-ish API for dispatching work synchronously (immediate)
or asynchronously (enqueue via the selected backend), while
respecting service-level defaults and project settings.

Typical usage
-------------

    from simcore_ai_django.services.mixins import ServiceExecutionMixin

    class MyService(DjangoBaseLLMService, ServiceExecutionMixin):
        execution_mode = None            # or "sync" / "async"
        execution_backend = None         # or "immediate" / "celery"
        execution_priority = None        # -100..100
        execution_run_after = None       # seconds or datetime
        require_enqueue = False          # force async if True

    # Run immediately (sync) using service+settings defaults
    MyService.execute(user_id=123)

    # Enqueue with per-call overrides
    MyService.using(backend="celery", run_after=60, priority=50).enqueue(user_id=123)

Implementation notes
--------------------
- Tracing is performed both here (lightweight wrapper spans) and within the
  global entrypoint (`simcore_ai_django.execution.entrypoint.execute`).  These
  spans are nested so you can see where calls originate from a service context.
- The heavy lifting (mode/backend resolution, queue mapping, priority support,
  and trace context propagation) is handled by the entrypoint.
"""

from typing import Any

from simcore_ai.tracing import service_span_sync
from simcore_ai_django.execution.entrypoint import execute as _execute
from simcore_ai.tracing import flatten_context


class ServiceExecutionMixin:
    """Mixin that adds ergonomic execution helpers to Django LLM services.

    Methods
    -------
    execute(**ctx):
        Execute the service immediately (sync) using resolved defaults.
        See `simcore_ai_django.execution.entrypoint.execute` for full resolution rules.

    using(**overrides) -> _ExecutionCall:
        Return a builder that captures per-call overrides (e.g., backend,
        run_after, priority). Call `.execute(**ctx)` or `.enqueue(**ctx)` on the
        builder to perform the action explicitly.
    """

    @classmethod
    def execute(cls, **ctx: Any) -> Any:
        """Run the service immediately (sync) via the global entrypoint.

        This wrapper adds a lightweight span so traces reveal the namespace
        (service-level dispatch) while the entrypoint performs the detailed
        orchestration and tracing of mode/backend selection.
        """
        # Build span attrs and drop None to avoid OTel NoneType warnings
        _identity = ".".join(
            x
            for x in (
                ctx.get("namespace"),
                ctx.get("kind") or ctx.get("service_bucket"),
                ctx.get("name") or ctx.get("service_name"),
            )
            if x
        ) or None

        attrs = {
            "service_cls": getattr(cls, "__name__", str(cls)),
            "ai.identity.service": _identity,
            "ai.identity.codec": ctx.get("codec_identity"),
            "req.correlation_id": ctx.get("correlation_id")
                                  or ctx.get("req_correlation_id")
                                  or ctx.get("request_correlation_id"),
            **flatten_context(ctx),
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}

        with service_span_sync(
                "exec.mux.execute",
                attributes=attrs,
        ):
            return _execute(cls, **ctx)

    @classmethod
    def using(cls, **overrides: Any):  # -> _ExecutionCall (runtime import to avoid cycle)
        """Return a builder that applies per-call execution overrides.

        Parameters
        ----------
        overrides: dict
            Supported keys mirror the entrypoint: `backend`, `queue_name`,
            `run_after` (seconds or datetime), `priority` (-100..100), and
            optional `enqueue` if you want to force async here.
        """
        from simcore_ai_django.execution.entrypoint import _ExecutionCall  # lazy import to avoid cycles

        keys = ",".join(sorted(map(str, overrides.keys()))) if overrides else ""
        uattrs = {
            "service_cls": getattr(cls, "__name__", str(cls)),
            "overrides.keys": keys,
            **flatten_context(overrides),
        }
        uattrs = {k: v for k, v in uattrs.items() if v is not None}

        # Tiny span so traces show builder creation in service context
        with service_span_sync(
                "exec.mux.using",
                attributes=uattrs,
        ):
            return _ExecutionCall(cls, dict(overrides or {}))
