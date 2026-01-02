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

        # Success! Store Response and mark for domain persistence
        # Phase 1: Store full Response object (atomic)
        with transaction.atomic():
            # Serialize Response to JSON if it's a Response object
            if hasattr(result, "model_dump"):
                result_json = result.model_dump()
            else:
                result_json = result

            call.result = result_json
            call.status = _STATUS_SUCCEEDED
            call.finished_at = timezone.now()

            record.update_from_call(call)
            record.status = _STATUS_SUCCEEDED
            record.result = result_json
            record.error = None
            record.finished_at = call.finished_at
            record.domain_persisted = False  # Mark for persistence worker
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
                "domain_persisted",
            ])

        logger.info(
            "Service call %s succeeded on attempt %d (domain persistence pending)",
            call_id,
            current_attempt
        )

        # Phase 2: Domain persistence happens in separate worker
        # (see process_pending_persistence task)

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


@task
def process_pending_persistence():
    """
    Process ServiceCallRecords that need domain persistence.

    This task runs periodically (e.g., every 10-30 seconds) and processes
    records where service execution succeeded but domain persistence hasn't
    happened yet.

    Design:
        - Idempotent: Uses PersistedChunk tracking for exactly-once semantics
        - Concurrent-safe: Uses select_for_update(skip_locked=True)
        - Retriable: LLM not re-called, only persistence retried
        - Two-phase: Response stored first (atomic), domain persistence separate

    Returns:
        dict with processing stats (processed, failed, pending, skipped)
    """
    from orchestrai.types import Response

    try:
        from orchestrai_django.apps import ensure_autostarted
        ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed in process_pending_persistence", exc_info=True)

    app = get_current_app()
    store = get_component_store(app)

    if not store:
        logger.error("No component store available, skipping persistence")
        return {"error": "No component store"}

    # Get persistence registry from component store
    try:
        from orchestrai.identity.domains import PERSIST_DOMAIN
        persistence_registry = store.registry(PERSIST_DOMAIN)
    except Exception as exc:
        logger.error(f"Failed to get persistence registry: {exc}", exc_info=True)
        return {"error": f"No persistence registry: {exc}"}

    # Configuration
    max_attempts = getattr(settings, "DOMAIN_PERSIST_MAX_ATTEMPTS", 10)
    batch_size = getattr(settings, "DOMAIN_PERSIST_BATCH_SIZE", 100)

    # Atomic claim of work with concurrent safety
    # - select_for_update(skip_locked=True) prevents race conditions
    # - Filter out exhausted records upfront to avoid wasted work
    with transaction.atomic():
        pending_records = list(
            ServiceCallRecord.objects.filter(
                status=_STATUS_SUCCEEDED,
                domain_persisted=False,
                domain_persist_attempts__lt=max_attempts,
            )
            .select_for_update(skip_locked=True)
            .order_by("finished_at")[:batch_size]
        )

        # Increment attempt counter for claimed records (inside lock)
        for record in pending_records:
            record.domain_persist_attempts += 1

        # Bulk update attempts (fast, within transaction)
        if pending_records:
            ServiceCallRecord.objects.bulk_update(
                pending_records, ["domain_persist_attempts"]
            )

    stats = {
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "claimed": len(pending_records),
    }

    # Process claimed records (outside lock, can take time)
    for record in pending_records:
        try:
            # Deserialize Response from JSON
            response = Response.model_validate(record.result)

            # Persist domain objects (schema-aware routing with idempotency)
            # The registry.persist() method will:
            # 1. Route to appropriate handler by (namespace, schema_identity)
            # 2. Handler uses ensure_idempotent() for exactly-once semantics
            # 3. Returns None if no handler found (skip gracefully)
            domain_obj = async_to_sync(persistence_registry.persist)(response)

            if domain_obj is None:
                # No handler found - not an error, just skip
                stats["skipped"] += 1
                logger.debug(
                    f"No persistence handler for call {record.id} "
                    f"(namespace={response.namespace}, "
                    f"schema={response.execution_metadata.get('schema_identity')})"
                )

                # Mark as persisted to avoid reprocessing
                with transaction.atomic():
                    record.domain_persisted = True
                    record.domain_persist_error = None
                    record.save(update_fields=["domain_persisted", "domain_persist_error"])
                continue

            # Success - mark as persisted
            with transaction.atomic():
                record.domain_persisted = True
                record.domain_persist_error = None
                record.save(update_fields=["domain_persisted", "domain_persist_error"])

            stats["processed"] += 1
            logger.info(
                f"Persisted domain objects for service call {record.id} "
                f"(attempt {record.domain_persist_attempts}/{max_attempts})"
            )

        except Exception as exc:
            # Persistence failed - log and track error
            stats["failed"] += 1
            logger.exception(
                f"Domain persistence failed for service call {record.id} "
                f"(attempt {record.domain_persist_attempts}/{max_attempts}): {exc}"
            )

            # Track error
            with transaction.atomic():
                record.domain_persist_error = str(exc)[:1000]  # Truncate long errors
                record.save(update_fields=["domain_persist_error"])

            # Check if exhausted
            if record.domain_persist_attempts >= max_attempts:
                logger.error(
                    f"Giving up on domain persistence for {record.id} "
                    f"after {max_attempts} attempts. Last error: {exc}"
                )
                # Mark as persisted to stop retrying (error tracked in domain_persist_error)
                with transaction.atomic():
                    record.domain_persisted = True  # Prevents infinite retries
                    record.save(update_fields=["domain_persisted"])

    logger.info(
        f"Domain persistence batch complete: "
        f"claimed={stats['claimed']}, processed={stats['processed']}, "
        f"failed={stats['failed']}, skipped={stats['skipped']}"
    )

    return stats


__all__ = ["run_service_call", "run_service_call_task", "process_pending_persistence"]
