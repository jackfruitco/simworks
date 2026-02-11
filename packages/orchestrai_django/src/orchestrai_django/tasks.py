from __future__ import annotations

import inspect
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from django.tasks import task
from django.utils import timezone

from orchestrai import get_current_app
from orchestrai.components.services.calls.mixins import _NullEmitter
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.active_app import get_component_store
from orchestrai.registry.services import ensure_service_registry

from orchestrai_django.models import (
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


def _resolve_response_schema(schema):
    """Best-effort unwrap of response schema (handles NativeOutput wrappers)."""
    from typing import get_args, get_origin

    if schema is None:
        return None

    if isinstance(schema, type):
        return schema

    for attr in ("inner_type", "type_", "schema", "output_type", "result_type", "type"):
        inner = getattr(schema, attr, None)
        if isinstance(inner, type):
            return inner

    origin = get_origin(schema)
    args = get_args(schema)
    if origin and args:
        for arg in args:
            if isinstance(arg, type):
                return arg

    return None


def _build_request_json(service, payload, context, request_obj):
    """Construct a request JSON payload for debugging."""
    from orchestrai.prompts.decorators import collect_prompts, render_prompt_methods

    prompt_text = ""
    try:
        prompts = getattr(service, "_prompt_methods", None) or collect_prompts(type(service))

        class _Ctx:
            def __init__(self, deps):
                self.deps = deps

        ctx = _Ctx(getattr(service, "context", None) or context)
        prompt_text = async_to_sync(render_prompt_methods)(service, prompts, ctx)
    except Exception:
        prompt_text = ""

    if request_obj is not None:
        try:
            request_json = request_obj.model_dump(mode="json")
        except TypeError:
            request_json = _manual_extract_fields(request_obj)

        if prompt_text:
            input_items = request_json.get("input")
            if isinstance(input_items, list):
                has_system = any(
                    isinstance(item, dict) and item.get("role") in ("system", "developer")
                    for item in input_items
                )
                if not has_system:
                    input_items.insert(0, {"role": "system", "content": prompt_text})
        return request_json

    schema_cls = getattr(service, "response_schema", None)
    schema_ident = None
    if schema_cls is not None:
        schema_ident = getattr(getattr(schema_cls, "identity", None), "as_str", None)
        if schema_ident is None:
            schema_ident = f"{schema_cls.__module__}.{schema_cls.__name__}"

    model = getattr(service, "effective_model", None)
    if callable(model):
        try:
            model = model()
        except Exception:
            model = getattr(service, "model", None)
    if model is None:
        model = getattr(service, "model", None)

    from orchestrai.utils.json import make_json_safe

    payload = payload or {}
    context = context or {}

    input_items = []
    if prompt_text:
        input_items.append({"role": "system", "content": prompt_text})

    message_history = payload.get("message_history") or context.get("message_history")
    if message_history:
        if isinstance(message_history, list):
            input_items.extend(message_history)
        else:
            input_items.append({"history": message_history})

    user_message = payload.get("user_message") or context.get("user_message")
    if user_message:
        input_items.append({"role": "user", "content": user_message})

    if not input_items:
        input_items = [payload]

    return make_json_safe(
        {
            "model": model,
            "input": input_items,
            "context": context,
            "response_schema": schema_ident,
            "use_native_output": bool(getattr(service, "use_native_output", False)),
            "tools": [],
        }
    )


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
    Execute a stored :class:`ServiceCall` with automatic retry logic.

    Uses ServiceCallAttempt to track individual execution attempts.
    Retries on failure up to ORCA_MAX_ATTEMPTS times (default: 4).
    Uses exponential backoff between retries.
    After max retries, marks call as failed and emits ai_response_failed signal.
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

    # Claim the call and allocate an attempt under a DB transaction
    with transaction.atomic():
        call = ServiceCallModel.objects.select_for_update().get(pk=call_id)

        # Check if already completed
        if call.status == CallStatus.COMPLETED:
            logger.info("Service call %s already completed, skipping", call_id)
            return call.to_jsonable()

        # Get current attempt count
        current_attempt_count = call.attempts.count()

        if current_attempt_count >= max_attempts:
            logger.warning(
                "Service call %s has reached max attempts (%d), marking as failed",
                call_id,
                max_attempts,
            )
            call.status = CallStatus.FAILED
            call.error = f"Max attempts ({max_attempts}) reached"
            call.finished_at = timezone.now()
            call.save(update_fields=["status", "error", "finished_at"])
            return call.to_jsonable()

        # Allocate new attempt
        try:
            attempt_record = call.allocate_attempt()
        except AttemptAllocationError:
            logger.warning("Service call %s: attempt allocation failed (already completed)", call_id)
            return call.to_jsonable()

        # Update call status
        if call.status != CallStatus.IN_PROGRESS:
            call.status = CallStatus.IN_PROGRESS
        call.started_at = call.started_at or timezone.now()

        # Populate related_object_id from context if not set
        if not call.related_object_id and call.context:
            sim_id = call.context.get("simulation_id")
            if sim_id:
                call.related_object_id = str(sim_id)

        call.save(update_fields=["status", "started_at", "related_object_id"])

    current_attempt = attempt_record.attempt
    logger.info(
        "Executing service call %s (attempt %d/%d)",
        call_id,
        current_attempt,
        max_attempts
    )

    service_cls = registry.get(Identity.get(call.service_identity))
    service = service_cls(**call.service_kwargs)

    if getattr(service, "emitter", None) is None:
        try:
            service.emitter = _NullEmitter()
        except Exception:
            pass

    try:
        payload = call.input or {}

        # Mark attempt as dispatched before calling the service
        attempt_record.mark_dispatched()

        # Prefer arun (Pydantic AI services), then aexecute, then execute
        if hasattr(service, "arun") and callable(service.arun):
            result = async_to_sync(service.arun)(**payload)
        elif hasattr(service, "aexecute") and callable(service.aexecute):
            aexecute = service.aexecute
            if inspect.iscoroutinefunction(aexecute):
                result = async_to_sync(aexecute)(**payload)
            else:  # pragma: no cover - defensive fallback
                result = aexecute(**payload)
        elif hasattr(service, "execute") and callable(service.execute):
            execute = service.execute
            if inspect.iscoroutinefunction(execute):
                result = async_to_sync(execute)(**payload)
            else:
                result = async_to_sync(service.aexecute)(**payload) if hasattr(service, "aexecute") else execute(**payload)
        else:  # pragma: no cover - defensive
            raise RuntimeError("Service does not implement arun/aexecute/execute")

        # Success! Store result and mark for domain persistence
        with transaction.atomic():
            # Serialize result to JSON
            call_output_data = None
            if hasattr(result, "model_dump"):
                try:
                    result_json = result.model_dump(mode="json")
                except TypeError as e:
                    if 'MockValSer' in str(e):
                        logger.warning("MockValSer error during result serialization, manually extracting fields")
                        result_json = _manual_extract_fields(result)
                    else:
                        raise
                call_output_data = result_json
            elif hasattr(result, "output") and hasattr(result, "all_messages_json"):
                # Pydantic AI AgentRunResult (dataclass)
                output = result.output
                if hasattr(output, "model_dump"):
                    output_json = output.model_dump(mode="json")
                elif isinstance(output, dict):
                    output_json = output
                else:
                    output_json = {"raw_value": str(output)}

                timestamp_val = result.timestamp() if callable(result.timestamp) else result.timestamp

                from orchestrai.utils.json import make_json_safe

                result_json = {
                    "output": output_json,
                    "messages": make_json_safe(result.all_messages_json()),
                    "run_id": str(result.run_id) if result.run_id else None,
                    "timestamp": timestamp_val.isoformat() if timestamp_val else None,
                }
                call_output_data = output_json
            elif isinstance(result, dict):
                result_json = result
                call_output_data = result
            else:
                logger.warning(
                    "Unknown result type %s, converting to string",
                    type(result).__name__
                )
                result_json = {"raw_value": str(result)}

            # Update attempt record with response data
            provider_meta = getattr(result, 'provider_meta', None) or {}
            usage = getattr(result, 'usage', None)

            # For AgentRunResult, usage is a method that returns RunUsage
            if callable(usage):
                usage = usage()

            provider_response_id = None
            if isinstance(provider_meta, dict):
                provider_response_id = (
                    provider_meta.get("id")
                    or provider_meta.get("response_id")
                    or provider_meta.get("request_id")
                )
            if not provider_response_id:
                for attr in ("provider_response_id", "response_id", "id"):
                    value = getattr(result, attr, None)
                    if value:
                        provider_response_id = value
                        break

            attempt_record.response_raw = result_json
            attempt_record.response_provider_raw = provider_meta.get("raw") if isinstance(provider_meta, dict) else None
            attempt_record.provider_response_id = provider_response_id
            attempt_record.finish_reason = provider_meta.get("finish_reason") if isinstance(provider_meta, dict) else None
            attempt_record.received_at = timezone.now()

            # Serialize structured_data/output if it's a Pydantic model
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
                if call_output_data is None:
                    call_output_data = attempt_record.structured_data

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

            # Lock call and mark as successful
            locked_call = ServiceCallModel.objects.select_for_update().get(pk=call_id)
            try:
                locked_call.mark_attempt_successful(
                    attempt_record,
                    call_output_data,
                    provider_response_id=provider_response_id
                )
            except AlreadySucceededError:
                logger.info(
                    "Service call %s: attempt %d finished but another attempt already succeeded",
                    call_id,
                    current_attempt
                )
                return locked_call.to_jsonable()

            # Refresh call after atomic update
            call.refresh_from_db()

            # Mark for domain persistence
            call.domain_persisted = False
            call.save(update_fields=["domain_persisted"])

        logger.info(
            "Service call %s succeeded on attempt %d, attempting inline persistence",
            call_id,
            current_attempt
        )

        # Populate attempt record with request data
        try:
            request_obj = getattr(result, 'request', None)
            request_json = _build_request_json(service, payload, call.context, request_obj)

            if request_json:
                attempt_record.request = request_json
                attempt_record.request_raw = request_json

                # Extract messages for easier querying
                messages_json = []
                if request_obj is not None and hasattr(request_obj, 'input') and request_obj.input:
                    for item in request_obj.input:
                        try:
                            messages_json.append(item.model_dump(mode="json"))
                        except (TypeError, AttributeError):
                            messages_json.append(str(item))
                else:
                    req_input = request_json.get("input")
                    if isinstance(req_input, list):
                        messages_json = req_input
                attempt_record.request_messages = messages_json

                # Extract tools for easier querying
                if request_obj is not None and hasattr(request_obj, 'tools') and request_obj.tools:
                    try:
                        attempt_record.request_tools = [t.model_dump(mode="json") for t in request_obj.tools]
                    except (TypeError, AttributeError):
                        attempt_record.request_tools = [str(t) for t in request_obj.tools]
                else:
                    req_tools = request_json.get("tools")
                    if isinstance(req_tools, list):
                        attempt_record.request_tools = req_tools

                # Get response schema identity if available
                if request_obj is not None and hasattr(request_obj, 'response_schema') and request_obj.response_schema:
                    schema_cls = _resolve_response_schema(request_obj.response_schema)
                    if schema_cls is not None:
                        identity = getattr(getattr(schema_cls, 'identity', None), 'as_str', None)
                        if identity is None:
                            identity = f"{schema_cls.__module__}.{schema_cls.__name__}"
                        attempt_record.schema_fqn = identity
                        call.schema_fqn = identity

                attempt_record.request_model = getattr(request_obj, 'model', None) or request_json.get("model")
                attempt_record.save()

            # Store attempt ID in context for persistence handlers
            if call.context is None:
                call.context = {}
            call.context["_service_call_attempt_id"] = attempt_record.id
            update_fields = ["context"]
            if call.schema_fqn:
                update_fields.append("schema_fqn")
            if request_json is not None:
                if call.request is None:
                    call.request = request_json
                elif call.request == request_json:
                    call.request = request_json
            if call.request is not None:
                update_fields.append("request")
            call.save(update_fields=update_fields)

        except Exception as req_err:
            logger.warning(f"Failed to populate request data for call {call_id}: {req_err}")

        # Attempt inline persistence via declarative persist_schema()
        try:
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

        # Check if we should retry
        remaining_attempts = max_attempts - current_attempt
        should_retry = remaining_attempts > 0 and (attempt_record is None or attempt_record.is_retryable)

        if should_retry:
            delay = _get_retry_delay(current_attempt)

            call.status = CallStatus.IN_PROGRESS
            call.error = f"Attempt {current_attempt} failed: {str(exc)}"
            call.save(update_fields=["status", "error"])

            logger.info(
                "Service call %s will retry (attempt %d/%d) after %ds backoff",
                call_id,
                current_attempt + 1,
                max_attempts,
                delay
            )

            run_service_call_task.enqueue(call_id=call_id)

            return call.to_jsonable()

        else:
            # Max retries reached - mark as failed and emit signal
            call.status = CallStatus.FAILED
            call.error = str(exc)
            call.finished_at = timezone.now()
            call.save(update_fields=[
                "status",
                "error",
                "finished_at",
            ])

            logger.error(
                "Service call %s failed after %d attempts, no more retries",
                call_id,
                current_attempt
            )

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

            return call.to_jsonable()


def _is_retryable_error(exc: Exception) -> bool:
    """Determine if an exception should trigger a retry."""
    non_retryable_types = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )

    if isinstance(exc, non_retryable_types):
        return False

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

    return True


@task
def process_pending_persistence():
    """Process ServiceCalls that need domain persistence.

    Runs periodically and processes calls where service execution succeeded
    but domain persistence hasn't happened yet. Uses the declarative
    ``persist_schema()`` engine.

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

    # Claim pending calls
    with transaction.atomic():
        pending_calls = list(
            ServiceCallModel.objects.filter(
                status=CallStatus.COMPLETED,
                domain_persisted=False,
                domain_persist_attempts__lt=max_attempts,
            )
            .exclude(schema_fqn__isnull=True)
            .exclude(schema_fqn="")
            .select_for_update(skip_locked=True)
            .order_by("finished_at")[:batch_size]
        )

        for call in pending_calls:
            call.domain_persist_attempts += 1

        if pending_calls:
            ServiceCallModel.objects.bulk_update(
                pending_calls, ["domain_persist_attempts"]
            )

    stats["claimed"] += len(pending_calls)

    for call in pending_calls:
        try:
            _inline_persist_service_call(call)
            stats["processed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.exception(
                "Domain persistence failed for call %s (attempt %d/%d): %s",
                call.id, call.domain_persist_attempts, max_attempts, exc,
            )
            with transaction.atomic():
                call.domain_persist_error = str(exc)[:1000]
                call.save(update_fields=["domain_persist_error"])

            if call.domain_persist_attempts >= max_attempts:
                logger.error("Giving up on persistence for %s after %d attempts", call.id, max_attempts)
                with transaction.atomic():
                    call.domain_persisted = True
                    call.save(update_fields=["domain_persisted"])

    logger.info(
        "Domain persistence batch complete: "
        "claimed=%d, processed=%d, failed=%d, skipped=%d",
        stats["claimed"], stats["processed"], stats["failed"], stats["skipped"],
    )

    return stats


def _inline_persist_service_call(call: ServiceCallModel):
    """Run declarative persist_schema() for a ServiceCall."""
    from orchestrai_django.persistence import PersistContext, persist_schema, resolve_schema_class

    if not call.schema_fqn or call.output_data is None:
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


__all__ = [
    "run_service_call",
    "run_service_call_task",
    "process_pending_persistence",
]
