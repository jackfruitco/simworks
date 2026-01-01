from __future__ import annotations

import inspect
import logging

from asgiref.sync import async_to_sync
from django.utils import timezone

from orchestrai import get_current_app
from orchestrai.components.services.calls import to_jsonable
from orchestrai.components.services.execution import _STATUS_FAILED, _STATUS_RUNNING, _STATUS_SUCCEEDED, _NullEmitter
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.active_app import get_component_store
from orchestrai.registry.services import ensure_service_registry

from orchestrai_django.models import ServiceCallRecord

logger = logging.getLogger(__name__)


def _debug_app_context(where: str) -> None:
    """Emit lightweight diagnostics about the current app and registry context."""

    try:
        app = get_current_app()
        store = get_component_store(app)
        svc_reg = None if store is None else store.registry(SERVICES_DOMAIN)
        count = None
        if svc_reg is not None:
            try:
                if hasattr(svc_reg, "count"):
                    count = svc_reg.count()  # type: ignore[assignment]
                else:
                    items = getattr(svc_reg, "items", lambda: [])()
                    count = len(list(items))
            except Exception:
                count = "<?>"

        logger.debug(
            "orchestrai_django ctx[%s]: app=%r app_id=%s store=%r store_id=%s svc_reg=%r svc_items=%s",
            where,
            app,
            None if app is None else hex(id(app)),
            store,
            None if store is None else hex(id(store)),
            None if svc_reg is None else type(svc_reg).__name__,
            count,
        )
    except Exception:
        logger.exception("orchestrai_django ctx[%s]: debug failed", where)


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

    try:
        from orchestrai_django.apps import ensure_autostarted

        ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed inside run_service_call", exc_info=True)

    _debug_app_context("run_service_call")

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
