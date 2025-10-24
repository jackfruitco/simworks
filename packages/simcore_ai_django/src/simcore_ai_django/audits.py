from __future__ import annotations

from typing import Any, Optional
from collections.abc import Iterable

from django.db import transaction

from simcore_ai.tracing import service_span_sync

from simcore_ai_django.models import AIRequestAudit, AIResponseAudit

# Django-rich DTOs (overlays)
from simcore_ai_django.types.django_dtos import (
    DjangoLLMRequest,
    DjangoLLMRequestMessage,
    DjangoLLMResponse,
    DjangoLLMResponseItem,
    DjangoLLMUsage,
)


# ----------------------------- serialization helpers -----------------------------

def _dump_json(obj: Any) -> Any:
    """
    Best-effort JSON-friendly conversion:

    - Pydantic v2 models => model_dump(mode="json")
    - Iterables of Pydantic models => list of model_dump
    - Plain dict/list/primitive => return as-is
    - Objects with __dict__ => dict(...)

    NOTE: This intentionally returns native Python (dict/list/str/int/None),
    not a JSON string, so it can be stored in Django JSONField.
    """
    if obj is None:
        return None

    # Pydantic v2 model
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()

    # Iterable of Pydantic models or primitives
    if isinstance(obj, (list, tuple)):
        return [_dump_json(x) for x in obj]

    # Mapping or primitive
    if isinstance(obj, (dict, str, int, float, bool)):
        return obj

    # Fallback for objects
    if hasattr(obj, "__dict__"):
        return {k: _dump_json(v) for k, v in vars(obj).items()}

    # Last resort
    return str(obj)


def _dump_messages(messages: Optional[Iterable[DjangoLLMRequestMessage]]) -> list[dict]:
    return [_dump_json(m) for m in (messages or [])]


def _dump_response_items(items: Optional[Iterable[DjangoLLMResponseItem]]) -> list[dict]:
    return [_dump_json(it) for it in (items or [])]


# ----------------------------- public audit helpers -----------------------------


def write_request_audit(dj_req: DjangoLLMRequest) -> int:
    """
    Persist an audit row for an outbound request and return its PK.

    - Stores normalized request messages (prefer rich messages if available).
    - Stores response_format* fields if they are already attached at emit time.
    """
    with service_span_sync(
        "ai.audit.request",
        attributes={
            "ai.namespace": getattr(dj_req, "namespace", None),
            "ai.provider_name": getattr(dj_req, "provider_name", None),
            "ai.client_name": getattr(dj_req, "client_name", None),
            "ai.model": getattr(dj_req, "model", None),
            "ai.stream": bool(getattr(dj_req, "stream", False)),
        },
    ):
        messages = dj_req.messages_rich or dj_req.messages or []
        tools = getattr(dj_req, "tools", None)  # if your DTO includes normalized tool specs

        row = AIRequestAudit.objects.create(
            # identity / routing
            correlation_id=dj_req.correlation_id,
            namespace=dj_req.namespace,
            namespace=dj_req.namespace,
            kind=dj_req.kind,
            service_name=dj_req.service_name,
            provider_name=dj_req.provider_name,
            client_name=dj_req.client_name,

            # domain linkage
            simulation_pk=dj_req.simulation_pk,

            # transport flags
            model=dj_req.model,
            stream=bool(getattr(dj_req, "stream", False)),

            # payloads
            messages=_dump_messages(messages),
            tools=_dump_json(tools),

            # response format (may be filled later by the client/provider)
            response_format_cls=getattr(dj_req, "response_format_cls", None).__name__
                if getattr(dj_req, "response_format_cls", None) else None,
            response_format_adapted=_dump_json(getattr(dj_req, "response_format_adapted", None)),
            response_format=_dump_json(getattr(dj_req, "response_format", None)),

            # prompt metadata (optional)
            prompt_meta=_dump_json(getattr(dj_req, "prompt_meta", None)),
        )
        return row.pk


def update_request_audit_formats(
    request_audit_pk: int,
    *,
    response_format_cls: Any | None,
    response_format_adapted: Any | None,
    response_format: Any | None,
) -> None:
    """
    Backfill/refresh the request audit row with final response format details
    (e.g., after provider-specific adapters/wrappers are applied).
    """
    with service_span_sync("ai.audit.request_update_formats"):
        cls_name = response_format_cls.__name__ if response_format_cls else None
        AIRequestAudit.objects.filter(pk=request_audit_pk).update(
            response_format_cls=cls_name,
            response_format_adapted=_dump_json(response_format_adapted),
            response_format=_dump_json(response_format),
        )


def write_response_audit(
    dj_resp: DjangoLLMResponse,
    *,
    request_audit_pk: int | None = None,
) -> int:
    """
    Persist an audit row for an inbound response and return its PK.

    - Stores normalized response items (prefer rich items if available).
    - Links to AIRequestAudit via FK when provided.
    """
    with service_span_sync(
        "ai.audit.response",
        attributes={
            "ai.namespace": getattr(dj_resp, "namespace", None),
            "ai.provider_name": getattr(dj_resp, "provider_name", None),
            "ai.client_name": getattr(dj_resp, "client_name", None),
            "ai.model": getattr(dj_resp, "model", None),
            "ai.error.present": bool(getattr(dj_resp, "error", None)),
        },
    ):
        request_row = None
        if request_audit_pk:
            request_row = AIRequestAudit.objects.filter(pk=request_audit_pk).first()

        outputs = dj_resp.outputs_rich or dj_resp.outputs or []
        usage = dj_resp.usage_rich or dj_resp.usage

        row = AIResponseAudit.objects.create(
            # link to request (nullable; keep on SET_NULL to preserve response if request audit is pruned)
            request=request_row,

            # identity / routing
            correlation_id=dj_resp.correlation_id,
            namespace=dj_resp.namespace,
            namespace=dj_resp.namespace,
            kind=dj_resp.kind,
            service_name=dj_resp.service_name,
            provider_name=dj_resp.provider_name,
            client_name=dj_resp.client_name,

            # domain linkage
            simulation_pk=dj_resp.simulation_pk,

            # normalized payloads
            outputs=_dump_response_items(outputs),
            usage=_dump_json(usage),
            provider_meta=_dump_json(getattr(dj_resp, "provider_meta", None)),

            # error
            error=getattr(dj_resp, "error", None),
        )
        return row.pk