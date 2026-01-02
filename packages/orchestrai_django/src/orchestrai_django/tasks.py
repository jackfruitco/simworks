from __future__ import annotations

import inspect
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from django.tasks import task
from django.utils import timezone

from orchestrai import get_current_app
from orchestrai.components.services.calls import to_jsonable
from orchestrai.components.services.calls.mixins import _STATUS_FAILED, _STATUS_RUNNING, _STATUS_SUCCEEDED, _NullEmitter
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.active_app import get_component_store
from orchestrai.registry.services import ensure_service_registry

from orchestrai_django.models import ServiceCallRecord
from django.db import transaction

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


def _get_max_retries() -> int:
    """Get max retry attempts from settings (default: 3)."""
    return getattr(settings, "DJANGO_TASKS_MAX_RETRIES", 3)


def _get_retry_delay() -> int:
    """Get retry delay in seconds from settings (default: 5)."""
    return getattr(settings, "DJANGO_TASKS_RETRY_DELAY", 5)


@task
def run_service_call_task(call_id: str):
    """
    Django task wrapper for run_service_call with retry logic.

    This is the entry point called by Django Tasks framework.
    """
    return run_service_call(call_id)


def run_service_call(call_id: str):
    """
    Execute a stored :class:`ServiceCallRecord` with automatic retry logic.

    Retries on failure up to DJANGO_TASKS_MAX_RETRIES times (default: 3).
    After max retries, marks record as failed and emits ai_response_failed signal.
    """

    try:
        from orchestrai_django.apps import ensure_autostarted

        ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed inside run_service_call", exc_info=True)

    _debug_app_context("run_service_call")

    app = get_current_app()
    registry = ensure_service_registry(app)

    # Claim the record under a DB transaction so select_for_update works.
    # We only hold the lock long enough to bump attempt/status timestamps.
    with transaction.atomic():
        record = ServiceCallRecord.objects.select_for_update().get(pk=call_id)

        # Check retry limit
        max_retries = _get_max_retries()
        current_attempt = (record.dispatch or {}).get("attempt", 0) + 1

        if current_attempt > max_retries:
            logger.warning(
                "Service call %s exceeded max retries (%d), marking as failed",
                call_id,
                max_retries,
            )
            record.status = "failed"
            record.error = f"Max retries ({max_retries}) exceeded"
            record.save(update_fields=["status", "error"])
            return to_jsonable(record.as_call())

        # Update attempt counter + mark running
        if record.dispatch is None:
            record.dispatch = {}
        record.dispatch["attempt"] = current_attempt
        record.status = _STATUS_RUNNING
        record.started_at = timezone.now()
        record.save(update_fields=["dispatch", "status", "started_at"])

    logger.info(
        "Executing service call %s (attempt %d/%d)",
        call_id,
        current_attempt,
        max_retries
    )

    service_cls = registry.get(Identity.get(record.service_identity))
    service = service_cls(**record.service_kwargs)

    call = record.as_call()
    call.id = record.id
    call.created_at = _normalize_dt(record.created_at)
    call.status = _STATUS_RUNNING
    call.started_at = record.started_at

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

        # Success!
        call.result = result
        call.status = _STATUS_SUCCEEDED
        call.finished_at = timezone.now()

        record.update_from_call(call)
        record.status = _STATUS_SUCCEEDED
        record.result = result
        record.error = None
        record.finished_at = call.finished_at
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

        logger.info("Service call %s succeeded on attempt %d", call_id, current_attempt)
        return to_jsonable(record.as_call())

    except Exception as exc:
        logger.exception(
            "Service call %s failed on attempt %d/%d: %s",
            call_id,
            current_attempt,
            max_retries,
            str(exc)
        )

        call.error = str(exc)
        call.status = _STATUS_FAILED
        call.finished_at = timezone.now()

        if current_attempt < max_retries:
            # Retry - re-enqueue the task
            record.status = "retrying"
            record.error = f"Attempt {current_attempt} failed: {str(exc)}"
            record.save(update_fields=["status", "error", "dispatch"])

            logger.info(
                "Service call %s will retry (attempt %d/%d)",
                call_id,
                current_attempt + 1,
                max_retries
            )

            # Re-enqueue via Django Tasks
            run_service_call_task.enqueue(call_id=call_id)

            return to_jsonable(call)

        else:
            # Max retries reached - mark as failed and emit signal
            record.status = _STATUS_FAILED
            record.error = str(exc)
            record.finished_at = call.finished_at
            record.save(update_fields=[
                "status",
                "error",
                "dispatch",
                "finished_at",
            ])

            logger.error(
                "Service call %s failed after %d attempts, no more retries",
                call_id,
                max_retries
            )

            # Emit failure signal for app-level handling
            try:
                from orchestrai_django.signals import ai_response_failed

                ai_response_failed.send(
                    sender=service.__class__,
                    call_id=call_id,
                    error=str(exc),
                    context=record.context or {}
                )
            except Exception:
                logger.exception("Failed to emit ai_response_failed signal")

            return to_jsonable(call)


__all__ = ["run_service_call", "run_service_call_task"]
