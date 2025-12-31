from __future__ import annotations

import inspect
import uuid
from datetime import datetime
from typing import Any
import logging

from asgiref.sync import async_to_sync

from orchestrai.components.services.calls import ServiceCall
from orchestrai.components.services.exceptions import ServiceConfigError

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


class ExecutionLifecycleMixin:
    """Async-first execution helpers that normalize service call records."""

    def _create_call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
        service: str | None = None,
        client: Any | None = None,
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
            client=client,
            request=request,
        )

    async def _run_call(
        self,
        *,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
    ) -> ServiceCall:
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
            client=getattr(self, "client", None),
        )
        call.status = _STATUS_RUNNING
        call.started_at = datetime.utcnow()

        client_override = getattr(self, "client", None)
        service_default = getattr(type(self), "provider_name", None) or getattr(
            self, "provider_name", None
        )
        resolved_client = resolve_call_client(
            self,
            call,
            client_override=client_override,
            service_default=service_default,
            required=False,
        )
        if resolved_client is not None:
            try:
                self.client = resolved_client  # type: ignore[attr-defined]
            except Exception:
                logger.debug("could not persist resolved client on service", exc_info=True)

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
        return async_to_sync(self._run_call)(payload=payload)


def _resolve_client_label(label: str | None) -> Any | None:
    """Resolve a client via registry/factory by label or provider slug."""

    provider_label = (label or "").strip()
    provider_ns = provider_label.split(".", 1)[0] if provider_label else ""

    if not provider_label:
        return None

    try:
        from orchestrai.client.registry import get_ai_client

        try:
            return get_ai_client(name=provider_label)
        except Exception:
            pass

        try:
            return get_ai_client(provider=provider_ns or provider_label)
        except Exception:
            pass
    except Exception:
        logger.debug("skipping registry client resolution (not configured)", exc_info=True)

    try:
        from orchestrai.client.factory import get_orca_client

        try:
            return get_orca_client(client=provider_label)
        except Exception:
            return get_orca_client(provider=provider_ns or provider_label)
    except Exception:
        logger.debug("factory client resolution failed; falling back", exc_info=True)

    return None


def _app_client(app: Any, name: str | None = None) -> Any | None:
    getter = getattr(app, "get_client", None)
    if callable(getter):
        try:
            return getter(name)
        except Exception:
            logger.debug("app.get_client lookup failed", exc_info=True)
    if name is None:
        try:
            return getattr(app, "client", None)
        except Exception:
            return None
    return None


def resolve_call_client(
    service: object,
    call: ServiceCall,
    *,
    client_override: Any | None = None,
    service_default: str | None = None,
    required: bool = False,
) -> Any | None:
    """Resolve and attach a client to *call* following orchestration policy."""

    from orchestrai._state import get_current_app

    app = get_current_app()
    mode = getattr(app, "mode", None)
    if callable(mode):
        try:
            mode = mode()
        except Exception:
            mode = None

    logger.debug(
        "🌀 resolving client for call %s (mode=%s, override=%s, default=%s)",
        call.id,
        mode,
        bool(client_override),
        service_default,
    )

    if mode == "single":
        client = _app_client(app)
        logger.debug(
            "🎯 single-orca mode detected; using app client %s", type(client).__name__
        )
        call.client = client
        if client is None and required:
            raise ServiceConfigError("No client available in single-orca mode")
        return client

    resolved: Any | None = None
    if client_override is not None:
        resolved = client_override if not isinstance(client_override, str) else None
        if resolved is None:
            resolved = _resolve_client_label(client_override)
        if resolved is None:
            resolved = _app_client(app, str(client_override))
        logger.debug("🚦 client override resolved to %s", type(resolved).__name__)

    if resolved is None and service_default:
        resolved = _resolve_client_label(service_default)
        if resolved is None:
            resolved = _app_client(app, service_default)
        logger.debug("🧭 service default resolved to %s", type(resolved).__name__)

    if resolved is None:
        resolved = _app_client(app)
        logger.debug("🌐 falling back to app default client %s", type(resolved).__name__)

    call.client = resolved

    if resolved is None and required:
        raise ServiceConfigError("No client available for service call")

    return resolved


__all__ = ["ExecutionLifecycleMixin", "resolve_call_client"]
