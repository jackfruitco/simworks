from __future__ import annotations

import asyncio
from datetime import datetime
import inspect
import logging
from typing import Any
import uuid

from orchestrai.components.services.calls import ServiceCall

logger = logging.getLogger(__name__)


class _NullEmitter:
    def emit_request(self, *args, **kwargs):
        return None

    def emit_response(self, *args, **kwargs):
        return None

    def emit_failure(self, *args, **kwargs):
        return None

    def emit_stream_chunk(self, *args, **kwargs):
        return None

    def emit_stream_complete(self, *args, **kwargs):
        return None


_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_SUCCEEDED = "succeeded"
_STATUS_FAILED = "failed"


class ServiceCallMixin:
    """
    Call-envelope helpers for services.

    This mixin is responsible for orchestrating :class:`ServiceCall` records
    around a service's lifecycle execution. It exposes public ``call`` / ``acall``
    entrypoints that wrap the service's ``execute`` / ``aexecute`` lifecycle
    (provided by :class:`~orchestrai.components.mixins.LifecycleMixin`).

    Key semantics:
      * ``execute`` / ``aexecute`` return the raw service result.
      * ``call`` / ``acall`` return a :class:`ServiceCall` record and inject the
        ``call`` into the execution payload so service logic can reference it.
    """

    async def acall(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
    ) -> ServiceCall:
        """Execute the service and return the populated :class:`ServiceCall`.

        The returned call record reflects status, timestamps, result/error, and
        dispatch metadata. The underlying service execution receives the same
        ``payload`` plus an injected ``call`` entry.
        """

        return await self._run_call(payload=payload, context=context, dispatch=dispatch)

    def call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
    ) -> ServiceCall:
        """Synchronous wrapper around :meth:`acall`."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.acall(payload=payload, context=context, dispatch=dispatch))

        if loop.is_running():
            raise RuntimeError("Cannot call service while an event loop is running")

        return loop.run_until_complete(
            self.acall(payload=payload, context=context, dispatch=dispatch)
        )

    def _create_call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
        service: str | None = None,
        request: Any | None = None,
    ) -> ServiceCall:
        safe_context: dict[str, Any] | None
        if context is None:
            safe_context = None
        elif isinstance(context, dict):
            safe_context = dict(context)
        else:
            try:
                safe_context = dict(context)
            except Exception:
                safe_context = {"value": context}

        try:
            safe_payload = dict(payload or {})
        except Exception:
            safe_payload = {"value": payload}

        return ServiceCall(
            id=uuid.uuid4().hex,
            status=_STATUS_PENDING,
            input=safe_payload,
            context=safe_context,
            result=None,
            error=None,
            dispatch=dispatch,
            created_at=datetime.utcnow(),
            service=service,
            request=request,
        )

    async def _run_call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
    ) -> ServiceCall:
        """Internal implementation for ``call`` / ``acall``."""
        identity = getattr(self, "identity", None)
        service_label = getattr(identity, "as_str", None) or self.__class__.__name__

        dispatch_payload: dict[str, Any] | None = None
        if dispatch:
            dispatch_payload = dict(dispatch)
        if dispatch_payload is None:
            dispatch_payload = {"service": service_label}
        else:
            dispatch_payload.setdefault("service", service_label)

        call = self._create_call(
            payload=payload,
            context=context,
            dispatch=dispatch_payload,
            service=service_label,
        )
        call.status = _STATUS_RUNNING
        call.started_at = datetime.utcnow()

        payload_with_call = dict(payload or {})
        payload_with_call.setdefault("call", call)

        if getattr(self, "emitter", None) is None:
            try:
                self.emitter = _NullEmitter()  # type: ignore[attr-defined]
            except Exception:
                pass

        try:
            if hasattr(self, "aexecute") and inspect.iscoroutinefunction(self.aexecute):
                result = await self.aexecute(**payload_with_call)
            elif hasattr(self, "execute") and callable(self.execute):
                exec_fn = self.execute
                if inspect.iscoroutinefunction(exec_fn):
                    result = await exec_fn(**payload_with_call)
                else:
                    result = exec_fn(**payload_with_call)
            else:  # pragma: no cover - defensive
                raise RuntimeError("Service does not implement execute/aexecute")

            call.result = result
            call.status = _STATUS_SUCCEEDED
        except Exception as exc:  # pragma: no cover - safety net
            call.error = str(exc)
            call.status = _STATUS_FAILED
        finally:
            call.finished_at = datetime.utcnow()

        return call

    def _sync_run_call(self, **payload: Any) -> ServiceCall:
        """Deprecated compatibility wrapper. Use :meth:`call` instead."""

        return self.call(payload=payload)


# Backwards compatibility
ExecutionLifecycleMixin = ServiceCallMixin
ExecutionLifecycleMixin.__doc__ = (
    "Deprecated alias for ServiceCallMixin. Prefer ServiceCallMixin.call/acall."
)


__all__ = ["ExecutionLifecycleMixin", "ServiceCallMixin"]
