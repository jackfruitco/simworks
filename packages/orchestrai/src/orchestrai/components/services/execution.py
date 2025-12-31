from __future__ import annotations

import inspect
import uuid
from datetime import datetime
from typing import Any

from asgiref.sync import async_to_sync

from orchestrai.components.services.calls import ServiceCall


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


class ExecutionLifecycleMixin:
    """Async-first execution helpers that normalize service call records."""

    def _create_call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
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
        )

    async def _run_call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
    ) -> ServiceCall:
        call = self._create_call(payload=payload, context=context, dispatch=dispatch)
        call.status = _STATUS_RUNNING
        call.started_at = datetime.utcnow()

        if getattr(self, "emitter", None) is None:
            try:
                self.emitter = _NullEmitter()  # type: ignore[attr-defined]
            except Exception:
                pass

        try:
            if hasattr(self, "aexecute") and inspect.iscoroutinefunction(self.aexecute):
                result = await self.aexecute(**(payload or {}))
            elif hasattr(self, "execute") and callable(self.execute):
                exec_fn = self.execute
                if inspect.iscoroutinefunction(exec_fn):
                    result = await exec_fn(**(payload or {}))
                else:
                    result = exec_fn(**(payload or {}))
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
        return async_to_sync(self._run_call)(payload=payload)


__all__ = ["ExecutionLifecycleMixin"]
