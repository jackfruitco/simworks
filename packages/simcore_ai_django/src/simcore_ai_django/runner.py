# simcore_ai_django/service_runner.py
from __future__ import annotations

import inspect
from typing import Any, Optional
from uuid import UUID

from django.conf import settings

# Core DTOs and client
from simcore_ai.client import AIClient
from simcore_ai.types import LLMRequest, LLMResponse
from simcore_ai.services import BaseLLMService
from simcore_ai.tracing import service_span_sync, service_span, extract_trace

# Codec execution helper
from .codecs.execute import execute_codec

# Django overlays
from .types import (
    promote_request,
    promote_response,
    demote_request,
    DjangoLLMRequest,
    DjangoLLMResponse,
)
from .audits import write_request_audit, update_request_audit_formats, write_response_audit
from .dispatch import (
    emit_request,
    emit_response_received,
    emit_response_ready,
    emit_failure,
)


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


def _resolve_namespace(service: BaseLLMService, namespace: Optional[str]) -> str:
    # Prefer explicit; else service.namespace; else fallback
    return namespace or getattr(service, "namespace", None) or "default"


# ------------------------------ sync facade -------------------------------

def run_service(
    service: BaseLLMService,
    *,
    traceparent: Optional[str] = None,
    namespace: Optional[str] = None,
    client_name: Optional[str] = None,
    provider_name: Optional[str] = None,
    simulation_pk: Optional[int] = None,
    correlation_id: Optional[UUID] = None,
    origin: Optional[str] = None,
    bucket: Optional[str] = None,
    service_name: Optional[str] = None,
) -> DjangoLLMResponse:
    """
    Orchestrate a full request/response flow for a Django-rich LLM service (SYNC).

    Steps:
      - service.build_request() -> LLMRequest
      - promote -> write request audit -> emit ai_request_sent
      - demote -> client.call(req)
      - promote response -> write response audit -> emit ai_response_received
      - codec.validate/parse/persist (optional) -> emit ai_response_ready
    """
    # If a traceparent was provided by the transport (e.g., Celery), extract it to continue the trace.
    if traceparent:
        try:
            extract_trace(traceparent)
        except Exception:
            pass

    ns = _resolve_namespace(service, namespace)
    codec = service.get_codec()
    codec_name = codec.__class__.__name__ if codec else None

    with service_span_sync(
        "ai.run_service",
        attributes={
            "ai.namespace": namespace or getattr(service, "namespace", None),
            "ai.service_name": getattr(service, "name", None),
            "ai.provider_name": provider_name or getattr(service, "provider_name", None),
            "ai.client_name": client_name or "default",
            "ai.codec_name": codec_name,
        },
    ):
        # 1) Build base request (service should construct messages/prompt and set response_format_cls)
        try:
            base_req: LLMRequest = _maybe_await(service.build_request())
        except Exception as e:
            emit_failure(
                error=f"{type(e).__name__}: {e}",
                namespace=ns,
                client_name=client_name or getattr(service, "client_name", None),
                provider_name=provider_name or getattr(service, "provider_name", None),
                simulation_pk=simulation_pk,
                correlation_id=correlation_id,
                request_audit_pk=None,
                origin=origin or getattr(service, "origin", None),
                bucket=bucket or getattr(service, "bucket", None),
                service_name=service_name or getattr(service, "name", service.__class__.__name__),
            )
            raise

        # 2) Promote to Django-rich request (attach routing/context overlays)
        dj_req: DjangoLLMRequest = promote_request(
            base_req,
            namespace=ns,
            client_name=client_name or getattr(service, "client_name", None),
            provider_name=provider_name or getattr(service, "provider_name", None),
            simulation_pk=simulation_pk,
            correlation_id=correlation_id,
            origin=origin or getattr(service, "origin", None),
            bucket=bucket or getattr(service, "bucket", None),
            service_name=service_name or getattr(service, "name", service.__class__.__name__),
        )

        # 3) Persist request audit
        with service_span_sync("ai.audit.request"):
            request_pk = write_request_audit(dj_req)

        # 4) Emit request sent
        with service_span_sync(
            "ai.emit.request_sent",
            attributes={"ai.namespace": dj_req.namespace, "ai.codec_name": codec_name},
        ):
            emit_request(
                request_dto=dj_req,
                request_audit_pk=request_pk,
                namespace=dj_req.namespace,
                client_name=dj_req.client_name,
                provider_name=dj_req.provider_name,
                simulation_pk=dj_req.simulation_pk,
                correlation_id=dj_req.correlation_id,
                origin=dj_req.origin,
                bucket=dj_req.bucket,
                service_name=dj_req.service_name,
                codec_name=codec_name,
            )

        # 5) Demote back to core request (strip Django overlays) before sending
        core_req: LLMRequest = demote_request(dj_req)

        # 6) Resolve client from service (registry-backed). Provider builds final schema internally.
        client: AIClient = service._get_client(codec)

        # 7) Send request (sync or async provider handled by `_maybe_await`)
        core_resp: LLMResponse = _maybe_await(client.call(core_req))

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
            client_name=dj_req.client_name,
            provider_name=dj_req.provider_name,
            simulation_pk=dj_req.simulation_pk,
            correlation_id=dj_req.correlation_id,
            request_db_pk=request_pk,
            origin=dj_req.origin,
            bucket=dj_req.bucket,
            service_name=dj_req.service_name,
        )

        # 9) Persist response audit
        with service_span_sync("ai.audit.response"):
            response_pk = write_response_audit(dj_resp, request_audit_pk=request_pk)

        # 10) Emit response received (pre-codec handling)
        with service_span_sync(
            "ai.emit.response_received",
            attributes={"ai.namespace": dj_resp.namespace, "ai.codec_name": codec_name},
        ):
            emit_response_received(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.simulation_pk,
                correlation_id=dj_resp.correlation_id,
                origin=dj_resp.origin,
                bucket=dj_resp.bucket,
                service_name=dj_resp.service_name,
            )

        # 11) Optional codec handling (validate/parse/persist)
        if codec:
            try:
                with service_span_sync(
                    "ai.codec.handle",
                    attributes={"ai.codec": codec_name, "ai.codec_name": codec_name},
                ):
                    execute_codec(
                        codec,
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
                    client_name=dj_resp.client_name,
                    provider_name=dj_resp.provider_name,
                    simulation_pk=dj_resp.simulation_pk,
                    correlation_id=dj_resp.correlation_id,
                    request_audit_pk=request_pk,
                    origin=dj_resp.origin,
                    bucket=dj_resp.bucket,
                    service_name=dj_resp.service_name,
                )

        # 12) Emit response ready (post-codec)
        with service_span_sync(
            "ai.emit.response_ready",
            attributes={"ai.namespace": dj_resp.namespace, "ai.codec_name": codec_name},
        ):
            emit_response_ready(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.simulation_pk,
                correlation_id=dj_resp.correlation_id,
                origin=dj_resp.origin,
                bucket=dj_resp.bucket,
                service_name=dj_resp.service_name,
            )

        return dj_resp


# ------------------------------ async facade ------------------------------

async def arun_service(
    service: BaseLLMService,
    *,
    traceparent: Optional[str] = None,
    namespace: Optional[str] = None,
    client_name: Optional[str] = None,
    provider_name: Optional[str] = None,
    simulation_pk: Optional[int] = None,
    correlation_id: Optional[UUID] = None,
    origin: Optional[str] = None,
    bucket: Optional[str] = None,
    service_name: Optional[str] = None,
) -> DjangoLLMResponse:
    """
    Async orchestration variant of run_service (awaits all awaitables).
    """
    # If a traceparent was provided by the transport (e.g., Celery), extract it to continue the trace.
    if traceparent:
        try:
            extract_trace(traceparent)
        except Exception:
            pass

    ns = _resolve_namespace(service, namespace)
    codec = service.get_codec()
    codec_name = codec.__class__.__name__ if codec else None

    async with service_span(
        "ai.arun_service",
        attributes={
            "ai.namespace": namespace or getattr(service, "namespace", None),
            "ai.service_name": getattr(service, "name", None),
            "ai.provider_name": provider_name or getattr(service, "provider_name", None),
            "ai.client_name": client_name or "default",
            "ai.codec_name": codec_name,
        },
    ):
        # Build base request
        try:
            base_req: LLMRequest = await _maybe_await_async(service.build_request())
        except Exception as e:
            emit_failure(
                error=f"{type(e).__name__}: {e}",
                namespace=ns,
                client_name=client_name or getattr(service, "client_name", None),
                provider_name=provider_name or getattr(service, "provider_name", None),
                simulation_pk=simulation_pk,
                correlation_id=correlation_id,
                request_audit_pk=None,
                origin=origin or getattr(service, "origin", None),
                bucket=bucket or getattr(service, "bucket", None),
                service_name=service_name or getattr(service, "name", service.__class__.__name__),
            )
            raise

        # Promote request
        dj_req: DjangoLLMRequest = promote_request(
            base_req,
            namespace=ns,
            client_name=client_name or getattr(service, "client_name", None),
            provider_name=provider_name or getattr(service, "provider_name", None),
            simulation_pk=simulation_pk,
            correlation_id=correlation_id,
            origin=origin or getattr(service, "origin", None),
            bucket=bucket or getattr(service, "bucket", None),
            service_name=service_name or getattr(service, "name", service.__class__.__name__),
        )

        async with service_span("ai.audit.request"):
            request_pk = write_request_audit(dj_req)
        async with service_span(
            "ai.emit.request_sent",
            attributes={"ai.namespace": dj_req.namespace, "ai.codec_name": codec_name},
        ):
            emit_request(
                request_dto=dj_req,
                request_audit_pk=request_pk,
                namespace=dj_req.namespace,
                client_name=dj_req.client_name,
                provider_name=dj_req.provider_name,
                simulation_pk=dj_req.simulation_pk,
                correlation_id=dj_req.correlation_id,
                origin=dj_req.origin,
                bucket=dj_req.bucket,
                service_name=dj_req.service_name,
                codec_name=codec_name,
            )

        core_req: LLMRequest = demote_request(dj_req)
        client: AIClient = service._get_client(codec)

        # Await call
        core_resp: LLMResponse = await _maybe_await_async(client.call(core_req))

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
            client_name=dj_req.client_name,
            provider_name=dj_req.provider_name,
            simulation_pk=dj_req.simulation_pk,
            correlation_id=dj_req.correlation_id,
            request_db_pk=request_pk,
            origin=dj_req.origin,
            bucket=dj_req.bucket,
            service_name=dj_req.service_name,
        )

        async with service_span("ai.audit.response"):
            response_pk = write_response_audit(dj_resp, request_audit_pk=request_pk)

        async with service_span(
            "ai.emit.response_received",
            attributes={"ai.namespace": dj_resp.namespace, "ai.codec_name": codec_name},
        ):
            emit_response_received(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.simulation_pk,
                correlation_id=dj_resp.correlation_id,
                origin=dj_resp.origin,
                bucket=dj_resp.bucket,
                service_name=dj_resp.service_name,
            )

        if codec:
            try:
                async with service_span(
                    "ai.codec.handle",
                    attributes={"ai.codec": codec_name, "ai.codec_name": codec_name},
                ):
                    await _maybe_await_async(
                        execute_codec(
                            codec,
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
                    client_name=dj_resp.client_name,
                    provider_name=dj_resp.provider_name,
                    simulation_pk=dj_resp.simulation_pk,
                    correlation_id=dj_resp.correlation_id,
                    request_audit_pk=request_pk,
                    origin=dj_resp.origin,
                    bucket=dj_resp.bucket,
                    service_name=dj_resp.service_name,
                )

        async with service_span(
            "ai.emit.response_ready",
            attributes={"ai.namespace": dj_resp.namespace, "ai.codec_name": codec_name},
        ):
            emit_response_ready(
                response_dto=dj_resp,
                request_audit_pk=request_pk,
                response_audit_pk=response_pk,
                namespace=dj_resp.namespace,
                client_name=dj_resp.client_name,
                provider_name=dj_resp.provider_name,
                simulation_pk=dj_resp.simulation_pk,
                correlation_id=dj_resp.correlation_id,
                origin=dj_resp.origin,
                bucket=dj_resp.bucket,
                service_name=dj_resp.service_name,
            )

        return dj_resp