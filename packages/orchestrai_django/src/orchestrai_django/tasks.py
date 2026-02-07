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

from orchestrai_django.models import (
    ServiceCallRecord,
    ServiceCallAttempt,
    ServiceCall as ServiceCallModel,
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

        # Prefer arun (Pydantic AI services), then aexecute, then execute
        if hasattr(service, "arun") and callable(service.arun):
            # New Pydantic AI-based services use arun
            result = async_to_sync(service.arun)(**payload)
        elif hasattr(service, "aexecute") and callable(service.aexecute):
            # Legacy services with aexecute
            aexecute = service.aexecute
            if inspect.iscoroutinefunction(aexecute):
                result = async_to_sync(aexecute)(**payload)
            else:  # pragma: no cover - defensive fallback
                result = aexecute(**payload)
        elif hasattr(service, "execute") and callable(service.execute):
            # Legacy services with sync execute
            execute = service.execute
            if inspect.iscoroutinefunction(execute):
                result = async_to_sync(execute)(**payload)
            else:
                result = async_to_sync(service.aexecute)(**payload) if hasattr(service, "aexecute") else execute(**payload)
        else:  # pragma: no cover - defensive
            raise RuntimeError("Service does not implement arun/aexecute/execute")

        # Success! Store Response and mark for domain persistence
        # Phase 1: Store full Response object (atomic)
        with transaction.atomic():
            # Serialize result to JSON
            # Handle different result types:
            # - Pydantic models: use model_dump(mode="json")
            # - AgentRunResult (dataclass): serialize manually
            # - dict: use directly
            if hasattr(result, "model_dump"):
                # Pydantic model (e.g., Response)
                try:
                    result_json = result.model_dump(mode="json")
                except TypeError as e:
                    # MockValSer error - manually extract fields as workaround
                    if 'MockValSer' in str(e):
                        logger.warning("MockValSer error during result serialization, manually extracting fields")
                        result_json = _manual_extract_fields(result)
                    else:
                        raise
            elif hasattr(result, "output") and hasattr(result, "all_messages_json"):
                # Pydantic AI AgentRunResult (dataclass)
                # Serialize to a dict with the key components
                # Note: some attributes are methods, some are properties
                output = result.output
                if hasattr(output, "model_dump"):
                    output_json = output.model_dump(mode="json")
                elif isinstance(output, dict):
                    output_json = output
                else:
                    output_json = {"raw_value": str(output)}

                # Get timestamp - it's a method, not a property
                timestamp_val = result.timestamp() if callable(result.timestamp) else result.timestamp

                # Import make_json_safe for handling bytes in messages (e.g., images)
                from orchestrai.utils.json import make_json_safe

                result_json = {
                    "output": output_json,
                    "messages": make_json_safe(result.all_messages_json()),
                    "run_id": str(result.run_id) if result.run_id else None,
                    "timestamp": timestamp_val.isoformat() if timestamp_val else None,
                }
            elif isinstance(result, dict):
                result_json = result
            else:
                # Fallback: try to convert to string representation
                logger.warning(
                    "Unknown result type %s, converting to string",
                    type(result).__name__
                )
                result_json = {"raw_value": str(result)}

            # Update attempt record with response data
            # Handle both old Response objects and new AgentRunResult
            provider_meta = getattr(result, 'provider_meta', None) or {}
            usage = getattr(result, 'usage', None)

            # For AgentRunResult, usage is a method that returns RunUsage
            if callable(usage):
                usage = usage()

            provider_response_id = provider_meta.get("id") if isinstance(provider_meta, dict) else None

            attempt_record.response_raw = result_json
            attempt_record.response_provider_raw = provider_meta.get("raw") if isinstance(provider_meta, dict) else None
            attempt_record.provider_response_id = provider_response_id
            attempt_record.finish_reason = provider_meta.get("finish_reason") if isinstance(provider_meta, dict) else None
            attempt_record.received_at = timezone.now()

            # Serialize structured_data/output if it's a Pydantic model
            # AgentRunResult uses 'output', older Response uses 'structured_data'
            structured_data = getattr(result, 'output', None) or getattr(result, 'structured_data', None)
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

        # Populate attempt record with request data
        try:
            request_obj = getattr(result, 'request', None)

            if request_obj:
                # Serialize request to JSON
                try:
                    request_json = request_obj.model_dump(mode="json")
                except TypeError:
                    request_json = _manual_extract_fields(request_obj)

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
                if hasattr(request_obj, 'tools') and request_obj.tools:
                    try:
                        attempt_record.request_tools = [t.model_dump(mode="json") for t in request_obj.tools]
                    except (TypeError, AttributeError):
                        attempt_record.request_tools = [str(t) for t in request_obj.tools]

                # Get response schema identity if available
                # Use module.classname format to match persistence handler registration
                if hasattr(request_obj, 'response_schema') and request_obj.response_schema:
                    schema_cls = request_obj.response_schema
                    # Try identity.as_str first (OrchestrAI schemas)
                    identity = getattr(getattr(schema_cls, 'identity', None), 'as_str', None)
                    if identity is None:
                        # Fall back to module.classname (Pydantic AI schemas)
                        identity = f"{schema_cls.__module__}.{schema_cls.__name__}"
                    attempt_record.request_schema_identity = identity

                attempt_record.request_model = getattr(request_obj, 'model', None)
                attempt_record.save()

            # Store attempt ID in context for persistence handlers
            if record.context is None:
                record.context = {}
            record.context["_service_call_attempt_id"] = attempt_record.id
            record.save(update_fields=["context"])

        except Exception as req_err:
            logger.warning(f"Failed to populate request data for call {call_id}: {req_err}")

        # Attempt inline persistence via declarative persist_schema()
        try:
            _inline_persist_record(record, attempt_record)
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
    """Process ServiceCallRecords and ServiceCalls that need domain persistence.

    Runs periodically and processes records where service execution succeeded
    but domain persistence hasn't happened yet. Uses the declarative
    ``persist_schema()`` engine instead of the old registry-based approach.

    Design:
        - Concurrent-safe: Uses select_for_update(skip_locked=True)
        - Retriable: LLM not re-called, only persistence retried
        - Two-phase: Response stored first (atomic), domain persistence separate

    Returns:
        dict with processing stats
    """
    try:
        from orchestrai_django.apps import ensure_autostarted
        ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed in process_pending_persistence", exc_info=True)

    max_attempts = getattr(settings, "DOMAIN_PERSIST_MAX_ATTEMPTS", 10)
    batch_size = getattr(settings, "DOMAIN_PERSIST_BATCH_SIZE", 100)

    stats = {
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "claimed": 0,
    }

    # --- Process legacy ServiceCallRecord ---
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

        for record in pending_records:
            record.domain_persist_attempts += 1

        if pending_records:
            ServiceCallRecord.objects.bulk_update(
                pending_records, ["domain_persist_attempts"]
            )

    stats["claimed"] += len(pending_records)

    for record in pending_records:
        try:
            _drain_persist_record(record)
            stats["processed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.exception(
                "Domain persistence failed for legacy call %s (attempt %d/%d): %s",
                record.id, record.domain_persist_attempts, max_attempts, exc,
            )
            with transaction.atomic():
                record.domain_persist_error = str(exc)[:1000]
                record.save(update_fields=["domain_persist_error"])

            if record.domain_persist_attempts >= max_attempts:
                logger.error("Giving up on persistence for %s after %d attempts", record.id, max_attempts)
                with transaction.atomic():
                    record.domain_persisted = True
                    record.save(update_fields=["domain_persisted"])

    # --- Process new ServiceCall ---
    with transaction.atomic():
        pending_calls = list(
            ServiceCallModel.objects.filter(
                status=CallStatus.COMPLETED,
                domain_persisted=False,
            )
            .exclude(schema_fqn__isnull=True)
            .exclude(schema_fqn="")
            .select_for_update(skip_locked=True)
            .order_by("finished_at")[:batch_size]
        )

    stats["claimed"] += len(pending_calls)

    for call in pending_calls:
        try:
            _inline_persist_service_call(call)
            stats["processed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.exception(
                "Domain persistence failed for call %s: %s",
                call.id, exc,
            )
            with transaction.atomic():
                call.domain_persist_error = str(exc)[:1000]
                call.save(update_fields=["domain_persist_error"])

    logger.info(
        "Domain persistence batch complete: "
        "claimed=%d, processed=%d, failed=%d, skipped=%d",
        stats["claimed"], stats["processed"], stats["failed"], stats["skipped"],
    )

    return stats


@task
def run_pydantic_ai_service_task(call_id: str):
    """
    Execute a Pydantic AI service call from the new ServiceCall model.

    This is the entry point for background execution of services using
    DjangoBaseService and the new simplified ServiceCall model.
    """
    return run_pydantic_ai_service_call(call_id)


def run_pydantic_ai_service_call(call_id: str):
    """
    Execute a stored :class:`ServiceCall` using Pydantic AI.

    This function works with the new unified ServiceCall model and
    Pydantic AI services. It provides a simpler execution path compared
    to the legacy run_service_call function.

    Key differences from legacy:
    - Single ServiceCall model (no separate attempts)
    - Pydantic AI handles validation retry internally
    - RunResult data stored directly on the model
    - Simpler error handling

    Args:
        call_id: The ServiceCall ID to execute.

    Returns:
        dict: JSON-serializable representation of the completed call.
    """

    try:
        from orchestrai_django.apps import ensure_autostarted
        ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed inside run_pydantic_ai_service_call", exc_info=True)

    _debug_app_context("run_pydantic_ai_service_call")

    app = get_current_app()
    registry = ensure_service_registry(app)

    # Claim the record under a DB transaction
    with transaction.atomic():
        call = ServiceCallModel.objects.select_for_update().get(pk=call_id)

        # Check if already completed
        if call.status == CallStatus.COMPLETED:
            logger.info("Service call %s already completed, skipping", call_id)
            return call.to_jsonable()

        # Mark as running
        call.mark_running()

        # Populate related_object_id from context if not set
        if not call.related_object_id and call.context:
            sim_id = call.context.get("simulation_id")
            if sim_id:
                call.related_object_id = str(sim_id)
                call.save(update_fields=["related_object_id"])

    logger.info("Executing Pydantic AI service call %s", call_id)

    # Resolve and instantiate service
    service_cls = registry.get(Identity.get(call.service_identity))
    service = service_cls(**call.service_kwargs)

    try:
        payload = call.input or {}

        # Execute the service
        if hasattr(service, "arun") and callable(service.arun):
            result = async_to_sync(service.arun)(**payload)
        else:
            raise RuntimeError("Service does not implement arun method")

        # Success! Extract data from Pydantic AI RunResult
        with transaction.atomic():
            locked_call = ServiceCallModel.objects.select_for_update().get(pk=call_id)

            # Check if already completed (concurrent execution)
            if locked_call.status == CallStatus.COMPLETED:
                logger.info("Service call %s completed by another worker", call_id)
                return locked_call.to_jsonable()

            # Extract data from RunResult
            output_data = None
            if hasattr(result, 'output') and result.output is not None:
                if hasattr(result.output, 'model_dump'):
                    try:
                        output_data = result.output.model_dump(mode="json")
                    except TypeError:
                        output_data = _manual_extract_fields(result.output)
                else:
                    output_data = result.output

            # Extract messages for conversation continuation
            messages_json = []
            if hasattr(result, 'new_messages') and callable(result.new_messages):
                try:
                    for msg in result.new_messages():
                        if hasattr(msg, 'model_dump'):
                            messages_json.append(msg.model_dump(mode="json"))
                        else:
                            messages_json.append(str(msg))
                except Exception as msg_err:
                    logger.warning(f"Failed to extract messages: {msg_err}")

            # Extract usage data
            usage_json = None
            if hasattr(result, 'usage') and callable(result.usage):
                usage = result.usage()
                if usage is not None:
                    if hasattr(usage, 'model_dump'):
                        try:
                            usage_json = usage.model_dump(mode="json")
                        except TypeError:
                            usage_json = {
                                "input_tokens": getattr(usage, 'input_tokens', 0),
                                "output_tokens": getattr(usage, 'output_tokens', 0),
                                "total_tokens": getattr(usage, 'total_tokens', 0),
                            }
                    else:
                        usage_json = usage

            # Extract model name
            model_name = None
            if hasattr(result, 'model_name'):
                model_name = result.model_name

            # Mark as completed
            locked_call.mark_completed(
                output_data=output_data,
                messages_json=messages_json,
                usage_json=usage_json,
                model_name=model_name,
            )

            # Mark for domain persistence
            locked_call.domain_persisted = False
            locked_call.save(update_fields=["domain_persisted"])

        logger.info("Pydantic AI service call %s completed successfully", call_id)

        # Attempt inline domain persistence via declarative persist_schema()
        try:
            call.refresh_from_db()
            _inline_persist_service_call(call)
        except Exception as persist_err:
            logger.warning(
                "Service call %s: inline persistence failed: %s (will retry via drain worker)",
                call_id,
                persist_err
            )

        return call.to_jsonable()

    except Exception as exc:
        logger.exception(
            "Pydantic AI service call %s failed: %s",
            call_id,
            str(exc)
        )

        # Mark as failed
        with transaction.atomic():
            locked_call = ServiceCallModel.objects.select_for_update().get(pk=call_id)
            locked_call.mark_failed(str(exc))

        # Emit failure signal
        try:
            from orchestrai_django.signals import ai_response_failed

            ai_response_failed.send(
                sender=service.__class__,
                call_id=call_id,
                error=str(exc),
                context=call.context or {}
            )
        except Exception:
            logger.exception("Failed to emit ai_response_failed signal")

        raise


def _resolve_schema_fqn_from_record(record: ServiceCallRecord) -> str | None:
    """Try to resolve a schema FQN from a legacy ServiceCallRecord."""
    # Try from the successful attempt's request_schema_identity
    if record.successful_attempt is not None:
        attempt = record.attempts.filter(attempt=record.successful_attempt).first()
        if attempt and attempt.request_schema_identity:
            return attempt.request_schema_identity

    # Try from all schema_ok attempts
    for attempt in record.attempts.filter(status=AttemptStatus.SCHEMA_OK):
        if attempt.request_schema_identity:
            return attempt.request_schema_identity

    return None


def _inline_persist_record(record: ServiceCallRecord, attempt_record=None):
    """Run declarative persist_schema() for a legacy ServiceCallRecord.

    Falls back to old registry-based persistence if no schema_fqn is
    available (for backwards compatibility during migration).
    """
    from orchestrai_django.persistence import PersistContext, persist_schema, resolve_schema_class

    # Determine schema FQN
    schema_fqn = _resolve_schema_fqn_from_record(record)
    if attempt_record and attempt_record.request_schema_identity:
        schema_fqn = attempt_record.request_schema_identity

    if not schema_fqn:
        # No schema info — mark as persisted to avoid infinite retries
        record.domain_persisted = True
        record.save(update_fields=["domain_persisted"])
        logger.debug("Service call %s: no schema_fqn, skipping persistence", record.id)
        return

    # Resolve schema class and validate data
    result_data = record.result or {}
    output_data = result_data.get("output", result_data)

    try:
        schema_cls = resolve_schema_class(schema_fqn)
    except (ImportError, AttributeError):
        logger.warning("Service call %s: could not resolve schema %s", record.id, schema_fqn)
        record.domain_persisted = True
        record.save(update_fields=["domain_persisted"])
        return

    schema_instance = schema_cls.model_validate(output_data)

    ctx = record.context or {}
    context = PersistContext(
        simulation_id=ctx.get("simulation_id", 0),
        call_id=record.id,
        audit_id=ctx.get("_ai_response_audit_id"),
        correlation_id=str(record.correlation_id) if record.correlation_id else None,
    )

    domain_obj = async_to_sync(persist_schema)(schema_instance, context)

    record.domain_persisted = True
    record.save(update_fields=["domain_persisted"])

    if domain_obj is not None:
        logger.info(
            "Service call %s: domain persistence complete (created %s)",
            record.id,
            type(domain_obj).__name__,
        )
    else:
        logger.debug("Service call %s: schema has no __persist__, skipped", record.id)


def _inline_persist_service_call(call: ServiceCallModel):
    """Run declarative persist_schema() for a ServiceCall."""
    from orchestrai_django.persistence import PersistContext, persist_schema, resolve_schema_class

    if not call.schema_fqn or not call.output_data:
        call.domain_persisted = True
        call.save(update_fields=["domain_persisted"])
        logger.debug("Service call %s: no schema_fqn or output_data, skipping", call.id)
        return

    try:
        schema_cls = resolve_schema_class(call.schema_fqn)
    except (ImportError, AttributeError):
        logger.warning("Service call %s: could not resolve schema %s", call.id, call.schema_fqn)
        call.domain_persisted = True
        call.save(update_fields=["domain_persisted"])
        return

    schema_instance = schema_cls.model_validate(call.output_data)

    ctx = call.context or {}
    context = PersistContext(
        simulation_id=ctx.get("simulation_id", 0),
        call_id=call.id,
        audit_id=ctx.get("_ai_response_audit_id"),
        correlation_id=str(call.correlation_id) if call.correlation_id else None,
    )

    domain_obj = async_to_sync(persist_schema)(schema_instance, context)

    call.domain_persisted = True
    call.save(update_fields=["domain_persisted"])

    if domain_obj is not None:
        logger.info(
            "Service call %s: domain persistence complete (created %s)",
            call.id,
            type(domain_obj).__name__,
        )
    else:
        logger.debug("Service call %s: schema has no __persist__, skipped", call.id)


def _drain_persist_record(record: ServiceCallRecord):
    """Drain worker helper: persist a legacy ServiceCallRecord."""
    _inline_persist_record(record)


__all__ = [
    "run_service_call",
    "run_service_call_task",
    "run_pydantic_ai_service_call",
    "run_pydantic_ai_service_task",
    "process_pending_persistence",
]
