# /packages/simcore_ai_django/src/simcore_ai_django/runner.py
"""
Django runner/orchestrator for LLM services.

Bridges `simcore_ai` core services and Django runtime concerns (audits, signals,
codec execution). Uses the core identity resolver so namespace/kind/name are canonical; by convention kind defaults to "default" unless explicitly set.

Sync entry:  run_service(service, ...)
Async entry: arun_service(service, ...)

Both build a provider‑agnostic LLMRequest via service.build_request(), promote/demote around provider boundaries, emit audits/signals, and (optionally) execute a codec resolved from the response identity.
"""
from __future__ import annotations

import inspect
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from django.conf import settings

# Core DTOs and client
from simcore_ai.client import AIClient
from simcore_ai.identity import resolve_identity
from simcore_ai.tracing import service_span_sync, service_span, extract_trace
from simcore_ai.types import LLMRequest, LLMResponse
from .audits import write_request_audit, update_request_audit_formats, write_response_audit
# Codec execution helper
from .codecs.execute import execute_codec
from .dispatch import (
    emit_request,
    emit_response_received,
    emit_response_ready,
    emit_failure,
)
# Django overlays
from .types import (
    promote_request,
    promote_response,
    demote_request,
    DjangoLLMRequest,
    DjangoLLMResponse,
)

if TYPE_CHECKING:
    from simcore_ai.services import BaseLLMService


# ------------------------------ utilities --------------------------------

def _maybe_await(obj):
    """Safely await coroutines; return plain values otherwise."""
    if inspect.isawaitable(obj):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(obj)
    return obj


async def _maybe_await_async(obj):
    """Await if coroutine; else return directly (for async entrypoint)."""
    if inspect.isawaitable(obj):
        return await obj
    return obj


# ------------------------------ sync facade -------------------------------

def run_service(
        service: BaseLLMService,
        *,
        traceparent: Optional[str] = None,
        namespace: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        client_name: Optional[str] = None,
        provider_name: Optional[str] = None,
        object_db_pk: Optional[int | UUID] = None,
        correlation_id: Optional[UUID] = None,
        context: Optional[dict] = None,
) -> DjangoLLMResponse:
    """
    Orchestrate a full request/response flow for a Django-rich LLM service (SYNC).

    This orchestrator bridges between the pure `simcore_ai` layer and Django runtime.

    Lifecycle summary:
      1. `service.build_request()` → returns **LLMRequest** (pure provider DTO)
      2. Promote → wrap in **DjangoLLMRequest** (adds ORM, audit, simulation, correlation info)
      3. Write audit + emit signals → maintain Django observability
      4. Demote → convert back to **LLMRequest** before calling the AI provider (provider-agnostic)
      5. Provider executes → returns **LLMResponse**
      6. Promote → wrap in **DjangoLLMResponse** for persistence, codecs, and dispatch

    Notes:
      • `LLMRequest` and `LLMResponse` remain provider-agnostic Pydantic DTOs.
      • `DjangoLLMRequest` and `DjangoLLMResponse` are enriched overlays used only within the Django runtime.
      • Promotion/demotion happens automatically before and after external boundaries.

    About DjangoBaseLLMService:
      - Inherits from `BaseLLMService` but adds Django-aware features (ORM access, audit hooks, signal dispatch).
      - It still builds and consumes the same `LLMRequest` / `LLMResponse` core DTOs to preserve portability.
      By convention, service `kind` defaults to "default" unless explicitly set.

    Steps:
      - service.build_request() -> LLMRequest
      - promote -> write request audit -> emit ai_request_sent
      - demote -> client.send_request(req)
      - promote response -> write response audit -> emit ai_response_received
      - codec.validate/parse/persist (optional) -> emit ai_response_ready
    """
    # Merge provided context onto the service (context-first, domain-agnostic)
    if context:
        try:
            base_ctx = dict(getattr(service, "context", None) or {})
            base_ctx.update(context)
            setattr(service, "context", base_ctx)
        except Exception:
            setattr(service, "context", context)

    # If a traceparent was provided by the transport (e.g., Celery), extract it to continue the trace.
    if traceparent:
        try:
            extract_trace(traceparent)
        except Exception:
            pass

    ident, _meta = resolve_identity(
        service.__class__,
        namespace=namespace,
        kind=kind,
        name=name,
    )
    ns, kd, nm = ident.namespace, ident.kind, ident.name
    identity_label = ident.to_string()

    # For early spans, prefer the configured codec label without resolving a concrete codec yet
    try:
        codec_name = service.get_codec_name()  # type: ignore[arg-type]
    except Exception:
        codec_name = None

    with service_span_sync(
            f"ai.run_service ({identity_label})",
            attributes={
                "ai.identity": identity_label,
                "ai.namespace": ns,
                "ai.kind": kd,
                "ai.name": nm,
                "ai.provider_name": provider_name or getattr(service, "provider_name", None),
                "ai.client_name": client_name or "default",
                "ai.codec_name": codec_name,
                **getattr(service, "flatten_context", lambda: {})(),
            },
    ):
        # 1) Build base request (service should construct messages/prompt and set response_format_cls)
        try:
            base_req: LLMRequest = _maybe_await(service.build_request())
        except Exception as e:
            emit_failure(
                error=f"{type(e).__name__}: {e}",
                namespace=ns,
                kind=kd,
                name=nm,
                client_name=client_name or getattr(service, "client_name", None),
                provider_name=provider_name or getattr(service, "provider_name", None),
                simulation_pk=object_db_pk,
                correlation_id=correlation_id,
                request_audit_pk=None,
            )
            raise

        # 2) Promote to Django-rich request (attach routing/context overlays)
        dj_req: DjangoLLMRequest = promote_request(
            base_req,
            namespace=ns,
            kind=kd,
            name=nm,
            client_name=client_name or getattr(service, "client_name", None),
            provider_name=provider_name or getattr(service, "provider_name", None),
            simulation_pk=object_db_pk,
            correlation_id=correlation_id,
        )

        # 3) Persist request audit
        with service_span_sync("ai.audit.request"):
            request_pk = write_request_audit(dj_req)

        # 4) Emit request sent
        with service_span_sync(
                "ai.emit.request_sent",
                attributes={
                    "ai.identity": f"{dj_req.namespace}.{dj_req.kind}.{dj_req.name}",
                    "ai.namespace": dj_req.namespace,
                    "ai.kind": dj_req.kind,
                    "ai.name": dj_req.name,
                    "ai.codec_name": codec_name,
                    **getattr(service, "flatten_context", lambda: {})(),
                },
        ):
            emit_request(
                request_dto=dj_req,
                request_audit_pk=request_pk,
                namespace=dj_req.namespace,
                kind=dj_req.kind,
                name=dj_req.name,
                client_name=dj_req.client_name,
                provider_name=dj_req.provider_name,
                simulation_pk=dj_req.object_db_pk,
                correlation_id=dj_req.correlation_id,
                codec_name=codec_name,
            )

        # 5) Demote back to core request (strip Django overlays) before sending
        core_req: LLMRequest = demote_request(dj_req)

        # 6) Resolve client from service (registry-backed). Provider builds final schema internally.
        client: AIClient = service.get_client()

        # 7) Send request (sync or async provider handled by `_maybe_await`)
        core_resp: LLMResponse = _maybe_await(client.send_request(core_req))

        # Optional: ensure request audit has final response format (providers may attach post-compile)
        with service_span_sync("ai.audit.request_update_formats"):
            update_request_audit_formats(
                request_pk,
                response_format_cls=getattr(core_req, "response_format_cls", None),
                response_format_adapted=getattr(core_req, "response_format_adapted", None),
                response_format=getattr(core_req, "response_format", None),
            )

        # 8) Promote response to Django-rich
        dj_resp: DjangoLLMResponse = promote_response(
            core_resp,
            namespace=ns,
            kind=kd,
            name=nm,
            client_name=dj_req.client_name,
            provider_name=dj_req.provider_name,
            object_db_pk=dj_req.object_db_pk,
            correlation_id=dj_req.correlation_id,
            request_db_pk=request_pk,
        )

        # 9) Persist response audit
        with service_span_sync("ai.audit.response"):
            response_pk = write_response_audit(dj_resp, request_audit_pk=request_pk)

        # 10) Emit response received (pre-codec handling)
        with service_span_sync(
                "ai.emit.response_received",
                attributes={
                    "ai.identity": f"{dj_resp.namespace}.{dj_resp.kind}.{dj_resp.name}",
                    "ai.namespace": dj_resp.namespace,
                    "ai.kind": dj_resp.kind,
                    "ai.name": dj_resp.name,
                    "ai.codec_name": codec_name,
                    **getattr(service, "flatten_context", lambda: {})(),
                },
        ):
            emit_response_received(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                kind=dj_resp.kind,
                name=dj_resp.name,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.object_db_pk,
                correlation_id=dj_resp.correlation_id,
            )

        # 11) Optional codec handling (validate/parse/persist) — prefer response-driven resolution
        codec_effective = None
        _resolver = getattr(service, "resolve_codec_for_response", None)
        if callable(_resolver):
            try:
                codec_effective = _resolver(core_resp)
            except Exception:
                codec_effective = None
        if codec_effective is None:
            try:
                codec_effective = service.get_codec()
            except Exception:
                codec_effective = None

        if codec_effective is not None:
            _codec_label = getattr(codec_effective, "__name__", codec_effective.__class__.__name__)
            try:
                with service_span_sync(
                        "ai.codec.handle",
                        attributes={"ai.codec": _codec_label, "ai.codec_name": _codec_label,
                                    **getattr(service, "flatten_context", lambda: {})()},
                ):
                    execute_codec(
                        codec_effective,
                        dj_resp,
                        context=dict(
                            request_audit_pk=request_pk,
                            response_audit_pk=response_pk,
                            namespace=ns,
                            service=service,
                            settings=settings,
                        ),
                    )
            except Exception as e:  # Emit failure but still return response
                emit_failure(
                    error=f"{type(e).__name__}: {e}",
                    namespace=ns,
                    kind=kd,
                    name=nm,
                    client_name=dj_resp.client_name,
                    provider_name=dj_resp.provider_name,
                    simulation_pk=dj_resp.object_db_pk,
                    correlation_id=dj_resp.correlation_id,
                    request_audit_pk=request_pk,
                )

        # 12) Emit response ready (post-codec)
        with service_span_sync(
                "ai.emit.response_ready",
                attributes={
                    "ai.identity": f"{dj_resp.namespace}.{dj_resp.kind}.{dj_resp.name}",
                    "ai.namespace": dj_resp.namespace,
                    "ai.kind": dj_resp.kind,
                    "ai.name": dj_resp.name,
                    "ai.codec_name": codec_name,
                    **getattr(service, "flatten_context", lambda: {})(),
                },
        ):
            emit_response_ready(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                kind=dj_resp.kind,
                name=dj_resp.name,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.object_db_pk,
                correlation_id=dj_resp.correlation_id,
            )

        return dj_resp


# ------------------------------ async facade ------------------------------

async def arun_service(
        service: BaseLLMService,
        *,
        traceparent: Optional[str] = None,
        namespace: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        client_name: Optional[str] = None,
        provider_name: Optional[str] = None,
        object_db_pk: Optional[int | UUID] = None,
        correlation_id: Optional[UUID] = None,
        context: Optional[dict] = None,
) -> DjangoLLMResponse:
    """
    Async orchestration variant of run_service (awaits all awaitables).
    By convention, service `kind` defaults to "default" unless explicitly set.
    """
    # Merge provided context onto the service (context-first, domain-agnostic)
    if context:
        try:
            base_ctx = dict(getattr(service, "context", None) or {})
            base_ctx.update(context)
            setattr(service, "context", base_ctx)
        except Exception:
            setattr(service, "context", context)

    # If a traceparent was provided by the transport (e.g., Celery), extract it to continue the trace.
    if traceparent:
        try:
            extract_trace(traceparent)
        except Exception:
            pass

    ident, _meta = resolve_identity(
        service.__class__,  # resolver works on class; instance attrs aren’t needed here
        namespace=namespace,
        kind=kind,
        name=name,
    )
    ns, kd, nm = ident.namespace, ident.kind, ident.name
    identity_label = ident.to_string()

    # For early spans, prefer the configured codec label without resolving a concrete codec yet
    try:
        codec_name = service.get_codec_name()  # type: ignore[arg-type]
    except Exception:
        codec_name = None

    async with service_span(
            f"ai.arun_service ({identity_label})",
            attributes={
                "ai.identity": identity_label,
                "ai.namespace": ns,
                "ai.kind": kd,
                "ai.name": nm,
                "ai.provider_name": provider_name or getattr(service, "provider_name", None),
                "ai.client_name": client_name or "default",
                "ai.codec_name": codec_name,
                **getattr(service, "flatten_context", lambda: {})(),
            },
    ):
        # Build base request
        try:
            base_req: LLMRequest = await _maybe_await_async(service.build_request())
        except Exception as e:
            emit_failure(
                error=f"{type(e).__name__}: {e}",
                namespace=ns,
                kind=kd,
                name=nm,
                client_name=client_name or getattr(service, "client_name", None),
                provider_name=provider_name or getattr(service, "provider_name", None),
                simulation_pk=object_db_pk,
                correlation_id=correlation_id,
                request_audit_pk=None,
            )
            raise

        # Promote request
        dj_req: DjangoLLMRequest = promote_request(
            base_req,
            namespace=ns,
            kind=kd,
            name=nm,
            client_name=client_name or getattr(service, "client_name", None),
            provider_name=provider_name or getattr(service, "provider_name", None),
            simulation_pk=object_db_pk,
            correlation_id=correlation_id,
        )

        async with service_span("ai.audit.request"):
            request_pk = write_request_audit(dj_req)
        async with service_span(
                "ai.emit.request_sent",
                attributes={
                    "ai.identity": f"{dj_req.namespace}.{dj_req.kind}.{dj_req.name}",
                    "ai.namespace": dj_req.namespace,
                    "ai.kind": dj_req.kind,
                    "ai.name": dj_req.name,
                    "ai.codec_name": codec_name,
                    **getattr(service, "flatten_context", lambda: {})(),
                },
        ):
            emit_request(
                request_dto=dj_req,
                request_audit_pk=request_pk,
                namespace=dj_req.namespace,
                kind=dj_req.kind,
                name=dj_req.name,
                client_name=dj_req.client_name,
                provider_name=dj_req.provider_name,
                simulation_pk=dj_req.object_db_pk,
                correlation_id=dj_req.correlation_id,
                codec_name=codec_name,
            )

        core_req: LLMRequest = demote_request(dj_req)
        client: AIClient = service.get_client()

        # Await call
        core_resp: LLMResponse = await _maybe_await_async(client.send_request(core_req))

        async with service_span("ai.audit.request_update_formats"):
            update_request_audit_formats(
                request_pk,
                response_format_cls=getattr(core_req, "response_format_cls", None),
                response_format_adapted=getattr(core_req, "response_format_adapted", None),
                response_format=getattr(core_req, "response_format", None),
            )

        dj_resp: DjangoLLMResponse = promote_response(
            core_resp,
            namespace=ns,
            kind=kd,
            name=nm,
            client_name=dj_req.client_name,
            provider_name=dj_req.provider_name,
            object_db_pk=dj_req.object_db_pk,
            correlation_id=dj_req.correlation_id,
            request_db_pk=request_pk,
        )

        async with service_span("ai.audit.response"):
            response_pk = write_response_audit(dj_resp, request_audit_pk=request_pk)

        async with service_span(
                "ai.emit.response_received",
                attributes={
                    "ai.identity": f"{dj_resp.namespace}.{dj_resp.kind}.{dj_resp.name}",
                    "ai.namespace": dj_resp.namespace,
                    "ai.kind": dj_resp.kind,
                    "ai.name": dj_resp.name,
                    "ai.codec_name": codec_name,
                    **getattr(service, "flatten_context", lambda: {})(),
                },
        ):
            emit_response_received(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                kind=dj_resp.kind,
                name=dj_resp.name,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.object_db_pk,
                correlation_id=dj_resp.correlation_id,
            )

        # Prefer response-driven codec resolution
        codec_effective = None
        _resolver = getattr(service, "resolve_codec_for_response", None)
        if callable(_resolver):
            try:
                codec_effective = _resolver(core_resp)
            except Exception:
                codec_effective = None
        if codec_effective is None:
            try:
                codec_effective = service.get_codec()
            except Exception:
                codec_effective = None

        if codec_effective is not None:
            _codec_label = getattr(codec_effective, "__name__", codec_effective.__class__.__name__)
            try:
                async with service_span(
                        "ai.codec.handle",
                        attributes={"ai.codec": _codec_label, "ai.codec_name": _codec_label,
                                    **getattr(service, "flatten_context", lambda: {})()},
                ):
                    await _maybe_await_async(
                        execute_codec(
                            codec_effective,
                            dj_resp,
                            context=dict(
                                request_audit_pk=request_pk,
                                response_audit_pk=response_pk,
                                namespace=ns,
                                service=service,
                                settings=settings,
                            ),
                        )
                    )
            except Exception as e:
                emit_failure(
                    error=f"{type(e).__name__}: {e}",
                    namespace=ns,
                    kind=kd,
                    name=nm,
                    client_name=dj_resp.client_name,
                    provider_name=dj_resp.provider_name,
                    simulation_pk=dj_resp.object_db_pk,
                    correlation_id=dj_resp.correlation_id,
                    request_audit_pk=request_pk,
                )

        async with service_span(
                "ai.emit.response_ready",
                attributes={
                    "ai.identity": f"{dj_resp.namespace}.{dj_resp.kind}.{dj_resp.name}",
                    "ai.namespace": dj_resp.namespace,
                    "ai.kind": dj_resp.kind,
                    "ai.name": dj_resp.name,
                    "ai.codec_name": codec_name,
                    **getattr(service, "flatten_context", lambda: {})(),
                },
        ):
            emit_response_ready(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                kind=dj_resp.kind,
                name=dj_resp.name,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.object_db_pk,
                correlation_id=dj_resp.correlation_id,
            )

        return dj_resp
