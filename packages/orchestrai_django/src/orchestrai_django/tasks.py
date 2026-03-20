from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import inspect
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.tasks import task
from django.utils import timezone
import structlog

from orchestrai import get_current_app
from orchestrai.components.services.calls.mixins import _NullEmitter
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.active_app import get_component_store
from orchestrai.registry.services import ensure_service_registry
from orchestrai_django.logging import service_span
from orchestrai_django.models import (
    AlreadySucceededError,
    AttemptAllocationError,
    AttemptStatus,
    CallStatus,
    ServiceCall as ServiceCallModel,
)
from orchestrai_django.signals import emit_service_call_dispatched, emit_service_call_succeeded
from orchestrai_django.utils.serialization import pydantic_model_to_dict

logger = logging.getLogger(__name__)

_SIM_DEBUG_CACHE_KEY = "orca:sim_debug:{}"


def _privacy_flag(name: str, default: bool = False) -> bool:
    return bool(getattr(settings, name, default))


def _is_sim_debug(simulation_id) -> bool:
    """Check if verbose debug logging is enabled for this simulation (via cache toggle)."""
    if not simulation_id:
        return False
    return bool(cache.get(_SIM_DEBUG_CACHE_KEY.format(simulation_id)))


class _SuppressFailureEmitter:
    """Emitter wrapper that suppresses per-attempt failure signals.

    In `run_service_call`, retries are managed here. We only want to emit
    `ai_response_failed` once on terminal failure (after retries exhausted),
    not on each transient attempt exception.
    """

    def __init__(self, delegate):
        self._delegate = delegate

    def emit_failure(self, *args, **kwargs):
        return None

    def __getattr__(self, item):
        return getattr(self._delegate, item)


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


def _extract_agent_config(service) -> dict | None:
    """Extract Pydantic AI Agent configuration from service for debugging.

    Captures model settings, system prompts, tools, and other Agent configuration.
    """
    from orchestrai.utils.json import make_json_safe

    config = {}

    try:
        # Get the Agent instance if it exists
        agent = getattr(service, "_agent", None) or getattr(service, "agent", None)

        if agent is None:
            return None

        # Model information
        config["model"] = str(getattr(agent, "model", None))
        config["model_settings"] = make_json_safe(getattr(agent, "model_settings", {}))

        # System prompts
        system_prompts = []
        if hasattr(agent, "system_prompts"):
            for prompt in agent.system_prompts:
                if callable(prompt):
                    system_prompts.append(
                        {"type": "callable", "name": getattr(prompt, "__name__", str(prompt))}
                    )
                else:
                    system_prompts.append({"type": "string", "content": str(prompt)[:500]})
        config["system_prompts"] = system_prompts

        # Tools
        tools_list = []
        if hasattr(agent, "tools"):
            for tool in agent.tools:
                tool_info = {
                    "name": getattr(tool, "__name__", str(tool)),
                    "type": type(tool).__name__,
                }
                if hasattr(tool, "__doc__") and tool.__doc__:
                    tool_info["description"] = tool.__doc__[:200]
                tools_list.append(tool_info)
        config["tools"] = tools_list

        # Result type / schema
        config["result_type"] = str(getattr(agent, "result_type", None))

        # Other settings
        config["retries"] = getattr(agent, "retries", None)
        config["result_tool_name"] = getattr(agent, "result_tool_name", None)
        config["result_tool_description"] = getattr(agent, "result_tool_description", None)

        return make_json_safe(config)

    except Exception as e:
        logger.debug(f"Failed to extract agent config: {e}")
        return {"error": str(e)}


def _build_request_json(service, payload, context, request_obj):
    """Construct a request JSON payload for debugging."""
    from orchestrai.components.instructions.base import BaseInstruction
    from orchestrai.components.instructions.collector import collect_instructions

    prompt_text = ""
    try:
        instruction_classes = getattr(
            service, "_instruction_classes", None
        ) or collect_instructions(type(service))
        parts: list[str] = []
        for instruction_cls in instruction_classes:
            has_custom_render = (
                hasattr(instruction_cls, "render_instruction")
                and instruction_cls.render_instruction is not BaseInstruction.render_instruction
            )
            if has_custom_render:
                result = instruction_cls.render_instruction(service)
                if inspect.isawaitable(result):

                    async def _await_render(awaitable):
                        return await awaitable

                    result = async_to_sync(_await_render)(result)
                if result:
                    parts.append(str(result))
            elif instruction_cls.instruction:
                parts.append(instruction_cls.instruction)
        prompt_text = "\n\n".join(parts)
    except Exception:
        prompt_text = ""

    if request_obj is not None:
        request_json = pydantic_model_to_dict(request_obj)

        if prompt_text:
            input_items = request_json.get("input")
            if isinstance(input_items, list):
                has_system = any(
                    isinstance(item, dict) and item.get("role") in ("system", "developer")
                    for item in input_items
                )
                if not has_system:
                    input_items.insert(0, {"role": "system", "content": prompt_text})
        if context:
            prev_id = context.get("previous_provider_response_id") or context.get(
                "previous_response_id"
            )
            if prev_id:
                request_json["previous_provider_response_id"] = prev_id
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

    request_json = {
        "model": model,
        "input": input_items,
        "context": context,
        "response_schema": schema_ident,
        "use_native_output": bool(getattr(service, "use_native_output", False)),
        "tools": [],
    }
    if context:
        prev_id = context.get("previous_provider_response_id") or context.get(
            "previous_response_id"
        )
        if prev_id:
            request_json["previous_provider_response_id"] = prev_id
    return make_json_safe(request_json)


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
                    items = getattr(svc_reg, "items", list)()
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


def _get_stale_attempt_threshold() -> int:
    """Return seconds before an in-flight attempt is considered stale (worker died)."""
    return getattr(settings, "ORCA_STALE_ATTEMPT_THRESHOLD", 300)  # 5 min default


@dataclass(frozen=True)
class ErrorClassification:
    system_retryable: bool
    user_retryable: bool
    reason_code: str


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
    Retries are immediate.
    After max retries, marks call as failed and emits ai_response_failed signal.
    """

    autostarted_app = None
    try:
        from orchestrai_django.apps import ensure_autostarted

        autostarted_app = ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed inside run_service_call", exc_info=True)

    _debug_app_context("run_service_call")

    app = autostarted_app or get_current_app()
    if autostarted_app is not None:
        logger.debug(
            "run_service_call resolved autostart app app_id=%s",
            hex(id(autostarted_app)),
        )
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

        # Guard against duplicate task dispatch (Celery at-least-once delivery).
        # If another worker already has an in-flight attempt, skip this one.
        # A staleness threshold allows re-dispatch if a worker dies without cleaning up.
        stale_cutoff = timezone.now() - timedelta(seconds=_get_stale_attempt_threshold())
        in_flight = call.attempts.filter(
            status__in=[AttemptStatus.BUILT, AttemptStatus.DISPATCHED],
            updated_at__gt=stale_cutoff,
        ).first()
        if in_flight is not None:
            logger.info(
                "Service call %s: attempt %d already in flight (status=%s), skipping duplicate dispatch",
                call_id,
                in_flight.attempt,
                in_flight.status,
            )
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
            logger.warning(
                "Service call %s: attempt allocation failed (already completed)", call_id
            )
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

    # Bind structured context for all log lines in this task execution
    sim_id = call.context.get("simulation_id") if call.context else None
    corr_id = str(call.correlation_id) if call.correlation_id else None
    structlog.contextvars.bind_contextvars(
        simulation_id=sim_id,
        correlation_id=corr_id,
        call_id=str(call_id),
        service_identity=call.service_identity,
    )

    sim_debug = _is_sim_debug(sim_id)

    logger.info("Executing service call %s (attempt %d/%d)", call_id, current_attempt, max_attempts)

    if sim_debug:
        logger.info(
            "[SIM_DEBUG] call_id=%s service=%s attempt=%d/%d sim_id=%s context=%s",
            call_id,
            call.service_identity,
            current_attempt,
            max_attempts,
            sim_id,
            call.context,
        )

    service_cls = registry.get(Identity.get(call.service_identity))
    service = service_cls(**call.service_kwargs)

    # Suppress service-level per-attempt failure emissions inside retry loop.
    # Terminal failure is emitted explicitly below when retries are exhausted.
    try:
        emitter = getattr(service, "emitter", None)
        if emitter is None:
            service.emitter = _NullEmitter()
        else:
            service.emitter = _SuppressFailureEmitter(emitter)
    except Exception:
        # Never break execution because of emitter decoration.
        logger.debug("Failed to decorate service emitter for call=%s", call_id, exc_info=True)

    span_attrs = {
        "service.identity": call.service_identity,
        "call_id": str(call_id),
        "attempt": current_attempt,
    }
    if sim_id is not None:
        span_attrs["simulation_id"] = str(sim_id)
    if corr_id is not None:
        span_attrs["correlation_id"] = corr_id

    try:
        payload = call.input or {}

        # Mark attempt as dispatched before calling the service
        attempt_record.mark_dispatched()
        emit_service_call_dispatched(call, attempt=attempt_record.attempt)

        # Execute service inside a parent OTEL span so that instrumented child spans
        # (e.g. openai.responses.create from logfire.instrument_openai) are grouped
        # under a single "Orca service call" trace in Logfire.  OTEL context propagates
        # through async_to_sync via Python contextvars (copied by asgiref).
        with service_span("orchestrai.service_call", attributes=span_attrs):
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
                    result = (
                        async_to_sync(service.aexecute)(**payload)
                        if hasattr(service, "aexecute")
                        else execute(**payload)
                    )
            else:  # pragma: no cover - defensive
                raise RuntimeError("Service does not implement arun/aexecute/execute")

        # Success! Store result and mark for domain persistence
        with transaction.atomic():
            # Serialize result to JSON
            call_output_data = None
            if hasattr(result, "model_dump"):
                result_json = pydantic_model_to_dict(result)
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

                timestamp_val = (
                    result.timestamp() if callable(result.timestamp) else result.timestamp
                )

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
                    "Unknown result type %s, converting to string", type(result).__name__
                )
                result_json = {"raw_value": str(result)}

            # Update attempt record with response data
            provider_meta = getattr(result, "provider_meta", None) or {}
            usage = getattr(result, "usage", None)

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
                response_obj = getattr(result, "response", None)
                response_id = getattr(response_obj, "provider_response_id", None)
                if response_id:
                    provider_response_id = response_id
            if not provider_response_id:
                for attr in ("provider_response_id", "response_id", "id"):
                    value = getattr(result, attr, None)
                    if value:
                        provider_response_id = value
                        break

            if _privacy_flag("PRIVACY_PERSIST_RAW_AI_RESPONSES"):
                attempt_record.response_raw = result_json
            if _privacy_flag("PRIVACY_PERSIST_PROVIDER_RAW"):
                attempt_record.response_provider_raw = (
                    provider_meta.get("raw") if isinstance(provider_meta, dict) else None
                )
            prev_provider_response_id = None
            if call.context:
                prev_provider_response_id = call.context.get(
                    "previous_provider_response_id"
                ) or call.context.get("previous_response_id")
            attempt_record.previous_provider_response_id = prev_provider_response_id
            attempt_record.provider_response_id = provider_response_id
            attempt_record.finish_reason = (
                provider_meta.get("finish_reason") if isinstance(provider_meta, dict) else None
            )
            attempt_record.received_at = timezone.now()

            # Serialize structured_data/output if it's a Pydantic model
            structured_data = getattr(result, "output", None) or getattr(
                result, "structured_data", None
            )
            if structured_data is not None:
                if hasattr(structured_data, "model_dump"):
                    attempt_record.structured_data = pydantic_model_to_dict(structured_data)
                elif isinstance(structured_data, dict):
                    attempt_record.structured_data = structured_data
                else:
                    attempt_record.structured_data = {"raw_value": str(structured_data)}
                if call_output_data is None:
                    call_output_data = attempt_record.structured_data

            # Token usage
            if usage:
                attempt_record.input_tokens = getattr(usage, "input_tokens", 0) or 0
                attempt_record.output_tokens = getattr(usage, "output_tokens", 0) or 0
                attempt_record.total_tokens = getattr(usage, "total_tokens", 0) or 0
                attempt_record.reasoning_tokens = getattr(usage, "reasoning_tokens", 0) or 0

            attempt_record.save()

            # Mark received before marking successful
            attempt_record.status = AttemptStatus.RECEIVED
            attempt_record.save(update_fields=["status", "updated_at"])

            # Lock call and mark as successful
            locked_call = ServiceCallModel.objects.select_for_update().get(pk=call_id)
            try:
                locked_call.mark_attempt_successful(
                    attempt_record, call_output_data, provider_response_id=provider_response_id
                )
            except AlreadySucceededError:
                logger.info(
                    "Service call %s: attempt %d finished but another attempt already succeeded",
                    call_id,
                    current_attempt,
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
            current_attempt,
        )

        if sim_debug:
            logger.info(
                "[SIM_DEBUG] call_id=%s service=%s succeeded"
                " input_tokens=%s output_tokens=%s total_tokens=%s",
                call_id,
                call.service_identity,
                attempt_record.input_tokens,
                attempt_record.output_tokens,
                attempt_record.total_tokens,
            )

        # Populate attempt record with request data
        try:
            request_obj = getattr(result, "request", None)
            request_json = _build_request_json(service, payload, call.context, request_obj)

            # Capture Agent configuration for debugging
            agent_config = _extract_agent_config(service)
            if agent_config and _privacy_flag("PRIVACY_PERSIST_RAW_AI_REQUESTS"):
                attempt_record.agent_config = agent_config

            # Capture Pydantic AI Request object (raw)
            if request_obj is not None and _privacy_flag("PRIVACY_PERSIST_RAW_AI_REQUESTS"):
                pydantic_request_json = pydantic_model_to_dict(request_obj)
                attempt_record.request_pydantic = pydantic_request_json

            if (
                request_obj is not None
                and hasattr(request_obj, "response_schema")
                and request_obj.response_schema
            ):
                schema_cls = _resolve_response_schema(request_obj.response_schema)
                if schema_cls is not None:
                    identity = getattr(getattr(schema_cls, "identity", None), "as_str", None)
                    if identity is None:
                        identity = f"{schema_cls.__module__}.{schema_cls.__name__}"
                    attempt_record.schema_fqn = identity
                    call.schema_fqn = identity

            if request_obj is not None:
                attempt_record.request_model = getattr(request_obj, "model", None)
            elif request_json:
                attempt_record.request_model = request_json.get("model")

            if request_json and _privacy_flag("PRIVACY_PERSIST_RAW_AI_REQUESTS"):
                attempt_record.request_input = request_json
                if _privacy_flag("PRIVACY_PERSIST_PROVIDER_RAW"):
                    attempt_record.request_provider = request_json

                # Extract messages for easier querying
                if _privacy_flag("PRIVACY_PERSIST_AI_MESSAGE_HISTORY"):
                    messages_json = []
                    if (
                        request_obj is not None
                        and hasattr(request_obj, "input")
                        and request_obj.input
                    ):
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
                if _privacy_flag("PRIVACY_PERSIST_RAW_AI_REQUESTS"):
                    if (
                        request_obj is not None
                        and hasattr(request_obj, "tools")
                        and request_obj.tools
                    ):
                        try:
                            attempt_record.request_tools = [
                                t.model_dump(mode="json") for t in request_obj.tools
                            ]
                        except (TypeError, AttributeError):
                            attempt_record.request_tools = [str(t) for t in request_obj.tools]
                    else:
                        req_tools = request_json.get("tools")
                        if isinstance(req_tools, list):
                            attempt_record.request_tools = req_tools

            attempt_record.save()

            # Store attempt ID in context for persistence handlers
            if call.context is None:
                call.context = {}
            call.context["_service_call_attempt_id"] = attempt_record.id
            update_fields = ["context"]
            if call.schema_fqn:
                update_fields.append("schema_fqn")
            if (
                request_json is not None
                and _privacy_flag("PRIVACY_PERSIST_RAW_AI_REQUESTS")
                and (call.request is None or call.request == request_json)
            ):
                call.request = request_json
            if call.request is not None:
                update_fields.append("request")
            if call.context.get("previous_provider_response_id") or call.context.get(
                "previous_response_id"
            ):
                call.previous_provider_response_id = call.context.get(
                    "previous_provider_response_id"
                ) or call.context.get("previous_response_id")
                update_fields.append("previous_provider_response_id")
            call.save(update_fields=update_fields)

        except Exception as req_err:
            logger.warning(f"Failed to populate request data for call {call_id}: {req_err}")

        # Attempt inline persistence via declarative persist_schema()
        try:
            _inline_persist_service_call(call)
        except Exception:
            logger.exception(
                "Service call %s: inline persistence failed (will retry via drain worker)",
                call_id,
                exc_info=True,
            )

        if call.domain_persisted:
            emit_service_call_succeeded(call, attempt=current_attempt)
        else:
            logger.debug(
                "Service call %s completed before domain persistence; success signal deferred",
                call_id,
            )

        return call.to_jsonable()

    except Exception as exc:
        logger.exception(
            "Service call %s failed on attempt %d/%d: %s",
            call_id,
            current_attempt,
            max_attempts,
            str(exc),
        )

        # Mark attempt as failed
        classification = _classify_error(exc)

        if attempt_record:
            attempt_record.mark_error(
                str(exc),
                is_retryable=classification.system_retryable,
            )

        # Check if we should retry
        remaining_attempts = max_attempts - current_attempt
        should_retry = remaining_attempts > 0 and (
            attempt_record is None or attempt_record.is_retryable
        )

        if should_retry:
            call.status = CallStatus.IN_PROGRESS
            call.error = f"Attempt {current_attempt} failed: {exc!s}"
            call.save(update_fields=["status", "error"])

            logger.info(
                "Service call %s will retry immediately (attempt %d/%d)",
                call_id,
                current_attempt + 1,
                max_attempts,
            )

            run_service_call_task.enqueue(call_id=call_id)

            return call.to_jsonable()

        else:
            # Max retries reached - mark as failed and emit signal
            call.status = CallStatus.FAILED
            call.error = str(exc)
            call.finished_at = timezone.now()
            call.save(
                update_fields=[
                    "status",
                    "error",
                    "finished_at",
                ]
            )

            logger.error(
                "Service call %s failed after %d attempts, no more retries",
                call_id,
                current_attempt,
            )

            # Emit failure signal
            try:
                from orchestrai_django.signals import ai_response_failed

                ai_response_failed.send(
                    sender=service.__class__,
                    call_id=call_id,
                    error=str(exc),
                    context=call.context or {},
                    reason_code=classification.reason_code,
                    user_retryable=classification.user_retryable,
                )
            except Exception:
                logger.exception("Failed to emit ai_response_failed signal")

            return call.to_jsonable()

    finally:
        # Always clear per-task structlog context to prevent leakage between tasks
        structlog.contextvars.clear_contextvars()


def _classify_error(exc: Exception) -> ErrorClassification:
    """Classify errors for system retry and user retry semantics."""
    non_retryable_types = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )

    if isinstance(exc, non_retryable_types):
        return ErrorClassification(
            system_retryable=False,
            user_retryable=False,
            reason_code="invalid_request",
        )

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
            return ErrorClassification(
                system_retryable=False,
                user_retryable=False,
                reason_code="provider_auth_or_request_error",
            )

    timeout_patterns = ["timeout", "timed out", "deadline exceeded"]
    for pattern in timeout_patterns:
        if pattern in error_str:
            return ErrorClassification(
                system_retryable=True,
                user_retryable=True,
                reason_code="provider_timeout",
            )

    network_patterns = [
        "connection",
        "temporarily unavailable",
        "service unavailable",
        "rate limit",
    ]
    for pattern in network_patterns:
        if pattern in error_str:
            return ErrorClassification(
                system_retryable=True,
                user_retryable=True,
                reason_code="provider_transient_error",
            )

    return ErrorClassification(
        system_retryable=True,
        user_retryable=True,
        reason_code="provider_unknown_error",
    )


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
    autostarted_app = None
    try:
        from orchestrai_django.apps import ensure_autostarted

        autostarted_app = ensure_autostarted()
    except Exception:
        logger.debug("ensure_autostarted failed in process_pending_persistence", exc_info=True)
    if autostarted_app is not None:
        logger.debug(
            "process_pending_persistence resolved autostart app app_id=%s",
            hex(id(autostarted_app)),
        )

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
            ServiceCallModel.objects.bulk_update(pending_calls, ["domain_persist_attempts"])

    stats["claimed"] += len(pending_calls)

    for call in pending_calls:
        try:
            _inline_persist_service_call(call)
            if call.domain_persisted:
                emit_service_call_succeeded(call)
            stats["processed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.exception(
                "Domain persistence failed for call %s (attempt %d/%d): %s",
                call.id,
                call.domain_persist_attempts,
                max_attempts,
                exc,
            )
            with transaction.atomic():
                call.domain_persist_error = str(exc)[:1000]
                call.save(update_fields=["domain_persist_error"])

            if call.domain_persist_attempts >= max_attempts:
                logger.error(
                    "Giving up on persistence for %s after %d attempts", call.id, max_attempts
                )
                with transaction.atomic():
                    call.domain_persisted = True
                    call.save(update_fields=["domain_persisted"])

    # Only log at INFO when there was actual work to do; idle cycles are DEBUG-only
    log_fn = logger.info if stats["claimed"] > 0 else logger.debug
    log_fn(
        "Domain persistence batch complete: claimed=%d, processed=%d, failed=%d, skipped=%d",
        stats["claimed"],
        stats["processed"],
        stats["failed"],
        stats["skipped"],
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
    extra = dict(ctx)
    extra.update(
        {
            "service_call_attempt_id": ctx.get("_service_call_attempt_id"),
            "provider_response_id": call.provider_response_id,
            "previous_provider_response_id": call.previous_provider_response_id,
        }
    )

    context = PersistContext(
        simulation_id=ctx.get("simulation_id", 0),
        call_id=call.id,
        audit_id=ctx.get("_ai_response_audit_id"),
        correlation_id=str(call.correlation_id) if call.correlation_id else None,
        extra=extra,
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
    "process_pending_persistence",
    "run_service_call",
    "run_service_call_task",
]
