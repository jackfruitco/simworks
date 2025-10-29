# simcore_ai_django/services/demote.py
from __future__ import annotations

"""
Service-level demotion helpers.

These helpers demote Django DTOs back into core `simcore_ai` request/response
models. They intentionally preserve the dot‑only identity string (namespace.kind.name),
provider/client metadata, and `received_at` on responses, aligning with the
core model decisions.
"""

from typing import Any, Dict

from simcore_ai.types import LLMRequest, LLMResponse
from simcore_ai_django.types.demote import (
    demote_request as _dto_demote_request,
    demote_response as _dto_demote_response,
)
from simcore_ai_django.types import DjangoLLMRequest, DjangoLLMResponse
from simcore_ai.tracing import service_span_sync


def _identity_label(ns: str | None, kd: str | None, nm: str | None) -> str:
    ns = (ns or "").strip()
    kd = (kd or "").strip()
    nm = (nm or "").strip()
    # Only dot-join non-empty parts to avoid leading/trailing dots in traces
    return ".".join([p for p in (ns, kd, nm) if p])


def _span_attrs_from_request(dj: DjangoLLMRequest) -> Dict[str, Any]:
    ident = _identity_label(getattr(dj, "namespace", None), getattr(dj, "kind", None), getattr(dj, "name", None))
    return {
        "ai.identity": ident or None,
        "dj.correlation_id": getattr(dj, "correlation_id", None),
        "dj.namespace": getattr(dj, "namespace", None),
        "dj.kind": getattr(dj, "kind", None),
        "dj.name": getattr(dj, "name", None),
        "dj.provider": getattr(dj, "provider_name", None),
        "dj.client": getattr(dj, "client_name", None),
        "db.object_db_pk": str(getattr(dj, "object_db_pk", None)) if getattr(dj, "object_db_pk", None) is not None else None,
        "db.request_pk": str(getattr(dj, "db_pk", None)) if getattr(dj, "db_pk", None) is not None else None,
    }


def _span_attrs_from_response(dj: DjangoLLMResponse) -> Dict[str, Any]:
    ident = _identity_label(getattr(dj, "namespace", None), getattr(dj, "kind", None), getattr(dj, "name", None))
    return {
        "ai.identity": ident or None,
        "dj.correlation_id": getattr(dj, "correlation_id", None),
        "dj.request_correlation_id": getattr(dj, "request_correlation_id", None),
        "dj.namespace": getattr(dj, "namespace", None),
        "dj.kind": getattr(dj, "kind", None),
        "dj.name": getattr(dj, "name", None),
        "dj.provider": getattr(dj, "provider_name", None),
        "dj.client": getattr(dj, "client_name", None),
        "db.object_db_pk": str(getattr(dj, "object_db_pk", None)) if getattr(dj, "object_db_pk", None) is not None else None,
        "db.request_pk": str(getattr(dj, "request_db_pk", None)) if getattr(dj, "request_db_pk", None) is not None else None,
        "db.response_pk": str(getattr(dj, "db_pk", None)) if getattr(dj, "db_pk", None) is not None else None,
    }


def demote_request_for_service(dj: DjangoLLMRequest) -> LLMRequest:
    """
    Demote a DjangoLLMRequest into a core LLMRequest.

    This is a thin wrapper over `simcore_ai_django.types.demote.demote_request` that
    preserves identity, provider/client, and returns a core LLMRequest with unchanged correlation id and codec hints.
    """
    with service_span_sync(
            "svc.demote_request_for_service",
            attributes=_span_attrs_from_request(dj),
    ):
        return _dto_demote_request(dj)


def demote_response_for_service(dj: DjangoLLMResponse) -> LLMResponse:
    """
    Demote a DjangoLLMResponse into a core LLMResponse.

    This is a thin wrapper over `simcore_ai_django.types.demote.demote_response` that
    preserves identity, provider/client metadata, and `received_at`, returning a core LLMResponse.
    """
    with service_span_sync(
            "svc.demote_response_for_service",
            attributes=_span_attrs_from_response(dj),
    ):
        return _dto_demote_response(dj)
