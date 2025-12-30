from __future__ import annotations

import inspect
from asgiref.sync import async_to_sync
from django.utils import timezone

from orchestrai import get_current_app
from orchestrai.components.services.calls import to_jsonable
from orchestrai.components.services.execution import _STATUS_FAILED, _STATUS_RUNNING, _STATUS_SUCCEEDED, _NullEmitter
from orchestrai.identity import Identity
from orchestrai.registry.services import ensure_service_registry

from orchestrai_django.models import ServiceCallRecord


def _normalize_dt(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        return value
    try:
        return timezone.make_aware(value)
    except Exception:
        return value


def run_service_call(call_id: str):
    """Entry point to execute a stored :class:`ServiceCallRecord`."""

    app = get_current_app()
    registry = ensure_service_registry(app)

    record = ServiceCallRecord.objects.get(pk=call_id)
    service_cls = registry.get(Identity.get(record.service_identity))
    service = service_cls(**record.service_kwargs)

    call = record.as_call()
    call.id = record.id
    call.created_at = _normalize_dt(record.created_at)
    call.status = _STATUS_RUNNING
    call.started_at = timezone.now()

    if getattr(service, "emitter", None) is None:
        try:
            service.emitter = _NullEmitter()
        except Exception:
            pass

    try:
        payload = record.input or {}

        if hasattr(service, "execute") and callable(service.execute):
            execute = service.execute
            if inspect.iscoroutinefunction(execute):
                result = async_to_sync(execute)(**payload)
            else:
                result = execute(**payload)
        elif hasattr(service, "aexecute") and callable(service.aexecute):
            aexecute = service.aexecute
            if inspect.iscoroutinefunction(aexecute):
                result = async_to_sync(aexecute)(**payload)
            else:  # pragma: no cover - defensive fallback
                result = aexecute(**payload)
        else:  # pragma: no cover - defensive
            raise RuntimeError("Service does not implement execute/aexecute")

        call.result = result
        call.status = _STATUS_SUCCEEDED
    except Exception as exc:  # pragma: no cover - defensive guard
        call.error = str(exc)
        call.status = _STATUS_FAILED
    finally:
        call.finished_at = timezone.now()

    record.update_from_call(call)
    record.save(update_fields=[
        "status",
        "input",
        "context",
        "result",
        "error",
        "dispatch",
        "backend",
        "queue",
        "task_id",
        "created_at",
        "started_at",
        "finished_at",
    ])
    return to_jsonable(record.as_call())


__all__ = ["run_service_call"]
