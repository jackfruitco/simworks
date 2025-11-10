# simcore_ai_django/runner.py
"""
Django runner/orchestrator for LLM services.

Bridges `simcore_ai` core services and Django runtime concerns (audits, signals, optional codec). Uses the core identity resolver so namespace/kind/name are canonical; by convention kind defaults to "default" unless explicitly set.

Sync entry:  run_service(service, ...)
Async entry: arun_service(service, ...)

Both build a provider‑agnostic LLMRequest via service.build_request(), promote/demote around provider boundaries, emit audits/signals, and (optionally) execute a codec resolved from the response identity.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING
from uuid import UUID

# Core DTOs and client
from simcore_ai.client import AIClient
from simcore_ai.identity import resolve_identity, Identity
from simcore_ai.tracing import service_span, extract_trace
from simcore_ai.types import LLMRequest, LLMResponse
from .audits import write_request_audit, update_request_audit_formats, write_response_audit
from .components import DjangoBaseCodec, DjangoBaseService
from .dispatch import (
    aemit_request,
    aemit_response_received,
    aemit_response_ready,
    aemit_failure,
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
    from simcore_ai.components import BaseService, BaseCodec

from asgiref.sync import async_to_sync, sync_to_async


# ------------------------------ sync facade -------------------------------

def run_service(
        service: BaseService,
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
    Sync adapter to the canonical async runner.
    Safe from any thread; no manual event loop management required.
    """
    return async_to_sync(arun_service)(
        service,
        traceparent=traceparent,
        namespace=namespace,
        kind=kind,
        name=name,
        client_name=client_name,
        provider_name=provider_name,
        object_db_pk=object_db_pk,
        correlation_id=correlation_id,
        context=context,
    )


# ------------------------------ async runner ------------------------------

async def arun_service(
        service: DjangoBaseService,
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

    # Resolve identity: use explicit overrides if provided; otherwise use the class's resolver-backed identity
    if namespace or kind or name:
        ident, _meta = resolve_identity(
            service.__class__,
            namespace=namespace,
            kind=kind,
            name=name,
            context=None,
        )
    else:
        # Leverage IdentityMixin cache on the class
        try:
            ident = service.__class__.resolve_identity()  # type: ignore[attr-defined]
            _meta = service.__class__.identity_meta()  # type: ignore[attr-defined]
        except Exception:
            # Final guard: resolve via helper without overrides
            ident, _meta = resolve_identity(service.__class__)
    ns, kd, nm = ident.as_tuple3
    identity_label = ident.as_str

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
            base_req: LLMRequest = await service.abuild_request()
        except Exception as e:
            await aemit_failure(
                error=f"{type(e).__name__}: {e}",
                namespace=ns,
                kind=kd,
                name=nm,
                client_name=client_name or getattr(service, "client_name", None),
                provider_name=provider_name or getattr(service, "provider_name", None),
                object_db_pk=object_db_pk,
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
            object_db_pk=object_db_pk,
            correlation_id=correlation_id,
        )

        async with service_span("ai.audit.request"):
            request_pk = await sync_to_async(write_request_audit)(dj_req)
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
            await aemit_request(
                request_dto=dj_req,
                request_audit_pk=request_pk,
                namespace=dj_req.namespace,
                kind=dj_req.kind,
                name=dj_req.name,
                client_name=dj_req.client_name,
                provider_name=dj_req.provider_name,
                object_db_pk=dj_req.object_db_pk,
                correlation_id=dj_req.correlation_id,
                codec_name=codec_name,
            )

        core_req: LLMRequest = demote_request(dj_req)
        client: AIClient = service.get_client()

        # Async-first client call
        core_resp: LLMResponse = await client.send_request(core_req)

        async with service_span("ai.audit.request_update_formats"):
            await sync_to_async(update_request_audit_formats)(
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
            response_pk = await sync_to_async(write_response_audit)(dj_resp, request_audit_pk=request_pk)

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
            await aemit_response_received(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                kind=dj_resp.kind,
                name=dj_resp.name,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                object_db_pk=dj_resp.object_db_pk,
                correlation_id=dj_resp.correlation_id,
            )

        codec: type[DjangoBaseCodec] | None = None
        if codec := Identity.resolve.try_for_(DjangoBaseCodec, dj_resp.identity):
            pass
        elif codec := Identity.resolve.try_for_(DjangoBaseCodec, service.codec):
            pass
        elif codec := Identity.resolve.try_for_(DjangoBaseCodec, service.identity):
            pass
        else:
            codec = None

        if codec is not None and issubclass(codec, DjangoBaseCodec):
            try:
                async with service_span(
                        "ai.codec.run",
                        attributes={
                            "ai.codec": codec.identity.as_str,
                            "ai.codec_cls": codec.identity.__class__.__name__,
                            **getattr(service, "flatten_context", lambda: {})(),
                        },
                ):
                    await codec.arun(resp=dj_resp)
            except Exception as e:
                await aemit_failure(
                    error=f"{type(e).__name__}: {e}",
                    namespace=ns,
                    kind=kd,
                    name=nm,
                    client_name=dj_resp.client_name,
                    provider_name=dj_resp.provider_name,
                    object_db_pk=dj_resp.object_db_pk,
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
            await aemit_response_ready(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                kind=dj_resp.kind,
                name=dj_resp.name,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                object_db_pk=dj_resp.object_db_pk,
                correlation_id=dj_resp.correlation_id,
            )

        return dj_resp
