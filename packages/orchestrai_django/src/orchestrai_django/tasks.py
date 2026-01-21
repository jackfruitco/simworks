from __future__ import annotations

import inspect
import logging
from uuid import uuid4

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

from orchestrai_django.models import (
    ServiceCallRecord,
    ServiceCallAttempt,
    AttemptStatus,
    CallStatus,
    AttemptAllocationError,
    AlreadySucceededError,
)
from django.db import transaction

logger = logging.getLogger(__name__)


def _manual_extract_fields(obj):
    """Manually extract fields from a Pydantic model when model_dump() fails with MockValSer."""
    from orchestrai.utils.json import make_json_safe

    result = {}
    if hasattr(obj, 'model_fields'):
        for field_name in obj.model_fields.keys():
            try:
                value = getattr(obj, field_name, None)
                # Handle nested Pydantic models
                if hasattr(value, 'model_dump'):
                    try:
                        # Use mode="json" to ensure UUID/datetime are converted
                        result[field_name] = value.model_dump(mode="json")
                    except TypeError:
                        # Nested model also has MockValSer - recurse
                        result[field_name] = _manual_extract_fields(value)
                elif isinstance(value, list):
                    result[field_name] = [
                        _manual_extract_fields(item) if hasattr(item, 'model_fields')
                        else make_json_safe(item)
                        for item in value
                    ]
                elif isinstance(value, dict):
                    result[field_name] = {
                        k: _manual_extract_fields(v) if hasattr(v, 'model_fields')
                        else make_json_safe(v)
                        for k, v in value.items()
                    }
                else:
                    result[field_name] = make_json_safe(value)
            except Exception as field_err:
                logger.warning(f"Failed to extract field {field_name}: {field_err}")
                result[field_name] = None
    return result


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


def _get_max_attempts() -> int:
    """Get max retry attempts from settings (default: 4)."""
    return getattr(settings, "ORCA_MAX_ATTEMPTS", 4)


def _get_retry_backoff_base() -> int:
    """Get retry backoff base in seconds from settings (default: 5)."""
    return getattr(settings, "ORCA_RETRY_BACKOFF_BASE", 5)


def _get_retry_delay(attempt: int) -> int:
    """Calculate exponential backoff delay: base * (2 ** (attempt - 1))."""
    base = _get_retry_backoff_base()
    return base * (2 ** (attempt - 1))


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

    Uses ServiceCallAttempt to track individual execution attempts.
    Retries on failure up to ORCA_MAX_ATTEMPTS times (default: 4).
    Uses exponential backoff between retries.
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

    max_attempts = _get_max_attempts()
    attempt_record = None

    # Claim the record and allocate an attempt under a DB transaction
    with transaction.atomic():
        record = ServiceCallRecord.objects.select_for_update().get(pk=call_id)

        # Check if already completed
        if record.status == CallStatus.COMPLETED:
            logger.info("Service call %s already completed, skipping", call_id)
            return to_jsonable(record.as_call())

        # Get current attempt count
        current_attempt_count = record.attempts.count()

        if current_attempt_count >= max_attempts:
            logger.warning(
                "Service call %s has reached max attempts (%d), marking as failed",
                call_id,
                max_attempts,
            )
            record.status = CallStatus.FAILED
            record.error = f"Max attempts ({max_attempts}) reached"
            record.finished_at = timezone.now()
            record.save(update_fields=["status", "error", "finished_at"])
            return to_jsonable(record.as_call())

        # Allocate new attempt
        try:
            attempt_record = record.allocate_attempt()
        except AttemptAllocationError:
            logger.warning("Service call %s: attempt allocation failed (already completed)", call_id)
            return to_jsonable(record.as_call())

        # Update record status
        if record.status != CallStatus.IN_PROGRESS:
            record.status = CallStatus.IN_PROGRESS
        record.started_at = record.started_at or timezone.now()

        # Populate related_object_id from context if not set
        if not record.related_object_id and record.context:
            sim_id = record.context.get("simulation_id")
            if sim_id:
                record.related_object_id = str(sim_id)

        record.save(update_fields=["status", "started_at", "related_object_id"])

    current_attempt = attempt_record.attempt
    logger.info(
        "Executing service call %s (attempt %d/%d)",
        call_id,
        current_attempt,
        max_attempts
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

        # Mark attempt as dispatched before calling the service
        attempt_record.mark_dispatched()

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
                try:
                    result_json = result.model_dump(mode="json")
                except TypeError as e:
                    # MockValSer error - manually extract fields as workaround
                    if 'MockValSer' in str(e):
                        logger.warning("MockValSer error during result serialization, manually extracting fields")
                        result_json = _manual_extract_fields(result)
                    else:
                        raise
            else:
                result_json = result

            # Update attempt record with response data
            provider_meta = getattr(result, 'provider_meta', None) or {}
            usage = getattr(result, 'usage', None)
            provider_response_id = provider_meta.get("id")

            attempt_record.response_raw = result_json
            attempt_record.response_provider_raw = provider_meta.get("raw")
            attempt_record.provider_response_id = provider_response_id
            attempt_record.finish_reason = provider_meta.get("finish_reason")
            attempt_record.received_at = timezone.now()

            # Serialize structured_data if it's a Pydantic model
            structured_data = getattr(result, 'structured_data', None)
            if structured_data is not None:
                if hasattr(structured_data, 'model_dump'):
                    try:
                        attempt_record.structured_data = structured_data.model_dump(mode="json")
                    except TypeError:
                        attempt_record.structured_data = _manual_extract_fields(structured_data)
                elif isinstance(structured_data, dict):
                    attempt_record.structured_data = structured_data
                else:
                    attempt_record.structured_data = {"raw_value": str(structured_data)}

            # Token usage
            if usage:
                attempt_record.input_tokens = getattr(usage, 'input_tokens', 0) or 0
                attempt_record.output_tokens = getattr(usage, 'output_tokens', 0) or 0
                attempt_record.total_tokens = getattr(usage, 'total_tokens', 0) or 0
                attempt_record.reasoning_tokens = getattr(usage, 'reasoning_tokens', 0) or 0

            attempt_record.save()

            # Mark received before marking successful
            attempt_record.status = AttemptStatus.RECEIVED
            attempt_record.save(update_fields=["status", "updated_at"])

            # Lock record and mark as successful
            locked_record = ServiceCallRecord.objects.select_for_update().get(pk=call_id)
            try:
                locked_record.mark_attempt_successful(
                    attempt_record,
                    result_json,
                    provider_response_id=provider_response_id
                )
            except AlreadySucceededError:
                # Another attempt already succeeded - this is fine
                logger.info(
                    "Service call %s: attempt %d finished but another attempt already succeeded",
                    call_id,
                    current_attempt
                )
                return to_jsonable(locked_record.as_call())

            # Refresh record after atomic update
            record.refresh_from_db()

            call.result = result_json
            call.status = _STATUS_SUCCEEDED
            call.finished_at = record.finished_at

            # Mark for domain persistence
            record.domain_persisted = False
            record.save(update_fields=["domain_persisted"])

        logger.info(
            "Service call %s succeeded on attempt %d, attempting inline persistence",
            call_id,
            current_attempt
        )

        # Create audit records for request/response tracking (dual-write phase)
        ai_response_audit_id = None
        try:
            from orchestrai_django.models import AIRequestAudit, AIResponseAudit

            # Get request from response (if attached)
            request_obj = getattr(result, 'request', None)
            ai_request = None

            if request_obj:
                # Serialize request to JSON
                try:
                    request_json = request_obj.model_dump(mode="json")
                except TypeError:
                    request_json = _manual_extract_fields(request_obj)

                # Also populate attempt record with request data
                attempt_record.request_raw = request_json

                # Extract messages for easier querying
                messages_json = []
                if hasattr(request_obj, 'input') and request_obj.input:
                    for item in request_obj.input:
                        try:
                            messages_json.append(item.model_dump(mode="json"))
                        except (TypeError, AttributeError):
                            messages_json.append(str(item))
                attempt_record.request_messages = messages_json

                # Extract tools for easier querying
                tools_json = None
                if hasattr(request_obj, 'tools') and request_obj.tools:
                    try:
                        tools_json = [t.model_dump(mode="json") for t in request_obj.tools]
                    except (TypeError, AttributeError):
                        tools_json = [str(t) for t in request_obj.tools]
                attempt_record.request_tools = tools_json

                # Get response schema identity if available
                response_schema_identity = None
                if hasattr(request_obj, 'response_schema') and request_obj.response_schema:
                    identity = getattr(getattr(request_obj.response_schema, 'identity', None), 'as_str', None)
                    response_schema_identity = identity
                    attempt_record.request_schema_identity = response_schema_identity

                attempt_record.request_model = getattr(request_obj, 'model', None)
                attempt_record.save()

                ai_request = AIRequestAudit(
                    correlation_id=request_obj.correlation_id,
                    service_identity=record.service_identity,
                    namespace=getattr(request_obj, 'namespace', None),
                    kind=getattr(request_obj, 'kind', None),
                    name=getattr(request_obj, 'name', None),
                    provider_name=getattr(result, 'provider_name', None),
                    client_name=getattr(result, 'client_name', None),
                    model=getattr(request_obj, 'model', None),
                    raw=request_json,
                    messages=messages_json,
                    tools=tools_json,
                    response_schema_identity=response_schema_identity,
                    object_db_pk=(record.context or {}).get("simulation_id"),
                    service_call=record,
                    dispatched_at=timezone.now(),
                )
                ai_request.save()
                logger.debug(f"Created AIRequestAudit {ai_request.id} for call {call_id}")
            else:
                # Create minimal request audit without full request data
                ai_request = AIRequestAudit(
                    correlation_id=getattr(result, 'request_correlation_id', None) or uuid4(),
                    service_identity=record.service_identity,
                    namespace=getattr(result, 'namespace', None),
                    provider_name=getattr(result, 'provider_name', None),
                    client_name=getattr(result, 'client_name', None),
                    raw={},  # No request data available
                    messages=[],
                    object_db_pk=(record.context or {}).get("simulation_id"),
                    service_call=record,
                    dispatched_at=timezone.now(),
                )
                ai_request.save()
                logger.debug(f"Created minimal AIRequestAudit {ai_request.id} for call {call_id}")

            # Create response audit
            ai_response = AIResponseAudit(
                ai_request=ai_request,
                service_call=record,
                correlation_id=result.correlation_id,
                request_correlation_id=getattr(result, 'request_correlation_id', None),
                raw=result_json,
                provider_raw=provider_meta.get("raw"),
                provider_name=getattr(result, 'provider_name', None),
                client_name=getattr(result, 'client_name', None),
                model=provider_meta.get("model"),
                finish_reason=provider_meta.get("finish_reason"),
                provider_response_id=provider_meta.get("id"),
                input_tokens=getattr(usage, 'input_tokens', 0) if usage else 0,
                output_tokens=getattr(usage, 'output_tokens', 0) if usage else 0,
                total_tokens=getattr(usage, 'total_tokens', 0) if usage else 0,
                reasoning_tokens=getattr(usage, 'reasoning_tokens', 0) if usage else 0,
                structured_data=attempt_record.structured_data,
                execution_metadata=getattr(result, 'execution_metadata', None) or {},
                received_at=getattr(result, 'received_at', None) or timezone.now(),
            )
            ai_response.save()
            ai_response_audit_id = ai_response.id
            logger.debug(f"Created AIResponseAudit {ai_response.id} for call {call_id}")

            # Store ID in context for persistence handlers
            if record.context is None:
                record.context = {}
            record.context["_ai_response_audit_id"] = ai_response_audit_id
            record.context["_service_call_attempt_id"] = attempt_record.id
            record.save(update_fields=["context"])

        except Exception as audit_err:
            logger.warning(f"Failed to create audit records for call {call_id}: {audit_err}")

        # Attempt inline persistence instead of deferring to drain worker
        try:
            from orchestrai.types import Response
            from orchestrai.identity.domains import PERSIST_DOMAIN

            response = Response.model_validate(record.result)
            store = get_component_store(app)
            persistence_registry = store.registry(PERSIST_DOMAIN) if store else None

            if persistence_registry:
                domain_obj = async_to_sync(persistence_registry.persist)(response)

                if domain_obj is not None:
                    record.domain_persisted = True
                    record.save(update_fields=["domain_persisted"])
                    logger.info(
                        "Service call %s: domain persistence complete (created %s)",
                        call_id,
                        type(domain_obj).__name__
                    )
                else:
                    # No handler found - mark as done to prevent retry loops
                    record.domain_persisted = True
                    record.save(update_fields=["domain_persisted"])
                    logger.debug(
                        "Service call %s: no persistence handler found for namespace=%s schema=%s",
                        call_id,
                        response.namespace,
                        response.execution_metadata.get("schema_identity") if response.execution_metadata else None
                    )
            else:
                logger.warning("Service call %s: no persistence registry available", call_id)
        except Exception as persist_err:
            logger.warning(
                "Service call %s: inline persistence failed: %s (will retry via drain worker)",
                call_id,
                persist_err
            )
            # Leave domain_persisted=False for drain worker retry

        return to_jsonable(record.as_call())

    except Exception as exc:
        logger.exception(
            "Service call %s failed on attempt %d/%d: %s",
            call_id,
            current_attempt,
            max_attempts,
            str(exc)
        )

        # Mark attempt as failed
        if attempt_record:
            is_retryable = _is_retryable_error(exc)
            attempt_record.mark_error(str(exc), is_retryable=is_retryable)

        call.error = str(exc)
        call.status = _STATUS_FAILED
        call.finished_at = timezone.now()

        # Check if we should retry
        remaining_attempts = max_attempts - current_attempt
        should_retry = remaining_attempts > 0 and (attempt_record is None or attempt_record.is_retryable)

        if should_retry:
            # Calculate backoff delay
            delay = _get_retry_delay(current_attempt)

            # Update record status for retry
            record.status = CallStatus.IN_PROGRESS
            record.error = f"Attempt {current_attempt} failed: {str(exc)}"
            record.save(update_fields=["status", "error"])

            logger.info(
                "Service call %s will retry (attempt %d/%d) after %ds backoff",
                call_id,
                current_attempt + 1,
                max_attempts,
                delay
            )

            # Schedule retry with backoff via Django Tasks
            # Note: Django Tasks doesn't support delay natively, so we use transaction.on_commit
            # with a simple approach. For production, consider Celery's countdown.
            def schedule_retry():
                import time
                time.sleep(delay)  # Blocking sleep - in production use proper delay
                run_service_call_task.enqueue(call_id=call_id)

            # For now, just re-enqueue immediately
            # TODO: Implement proper delay mechanism
            run_service_call_task.enqueue(call_id=call_id)

            return to_jsonable(call)

        else:
            # Max retries reached - mark as failed and emit signal
            record.status = CallStatus.FAILED
            record.error = str(exc)
            record.finished_at = call.finished_at
            record.save(update_fields=[
                "status",
                "error",
                "finished_at",
            ])

            logger.error(
                "Service call %s failed after %d attempts, no more retries",
                call_id,
                current_attempt
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


def _is_retryable_error(exc: Exception) -> bool:
    """Determine if an exception should trigger a retry.

    Args:
        exc: The exception that occurred.

    Returns:
        True if the error is retryable, False otherwise.
    """
    # Common non-retryable errors
    non_retryable_types = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )

    if isinstance(exc, non_retryable_types):
        return False

    # Check for specific error messages indicating non-retryable conditions
    error_str = str(exc).lower()
    non_retryable_patterns = [
        "invalid api key",
        "authentication",
        "unauthorized",
        "forbidden",
        "not found",
        "invalid request",
        "bad request",
    ]

    for pattern in non_retryable_patterns:
        if pattern in error_str:
            return False

    # Default to retryable
    return True


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
    # - Accept both old 'succeeded' status and new CallStatus.COMPLETED
    with transaction.atomic():
        pending_records = list(
            ServiceCallRecord.objects.filter(
                status__in=[_STATUS_SUCCEEDED, CallStatus.COMPLETED],
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
