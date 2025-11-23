# simcore_ai_django/services/demote.py


"""
Service-level demotion helpers.

These helpers demote Django DTOs back into core `simcore_ai` request/response
models. They intentionally preserve the dot‑only identity string (namespace.kind.name),
provider/client metadata, and `received_at` on responses, aligning with the
core model decisions.
"""

from typing import Any

from simcore_ai.types import Request, Response
from simcore_ai_django.types.demote import (
    demote_request as _dto_demote_request,
    demote_response as _dto_demote_response,
)
from simcore_ai_django.types import DjangoRequest, DjangoResponse
from simcore_ai.tracing import service_span_sync
from simcore_ai.identity import Identity


def _identity_str(ns: str | None, kd: str | None, nm: str | None) -> str | None:
    """Best-effort dot identity.

    If all three parts are present, validate/normalize via `Identity` and
    return `identity.as_str`. Otherwise, join only the present parts to
    avoid misleading defaults in traces.
    """
    parts = [p.strip() for p in (ns or "", kd or "", nm or "") if p and p.strip()]
    if len(parts) == 3:
        try:
            ident = Identity.get_for(value=(parts[0], parts[1], parts[2]))
            return ident.as_str
        except Exception:
            # Fall through to best-effort join if validation fails
            pass
    return ".".join(parts) if parts else None


def _span_attrs_from_request(dj: DjangoRequest) -> dict[str, Any]:
    ident = _identity_str(getattr(dj, "namespace", None), getattr(dj, "kind", None), getattr(dj, "name", None))
    return {
        "simcore.identity": ident or None,
        "dj.correlation_id": getattr(dj, "correlation_id", None),
        "dj.namespace": getattr(dj, "namespace", None),
        "dj.kind": getattr(dj, "kind", None),
        "dj.name": getattr(dj, "name", None),
        "dj.provider": getattr(dj, "provider_name", None),
        "dj.client": getattr(dj, "client_name", None),
        "db.object_db_pk": str(getattr(dj, "object_db_pk", None)) if getattr(dj, "object_db_pk", None) is not None else None,
        "db.request_pk": str(getattr(dj, "db_pk", None)) if getattr(dj, "db_pk", None) is not None else None,
    }


def _span_attrs_from_response(dj: DjangoResponse) -> dict[str, Any]:
    ident = _identity_str(getattr(dj, "namespace", None), getattr(dj, "kind", None), getattr(dj, "name", None))
    return {
        "simcore.identity": ident or None,
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


def demote_request_for_service(dj: DjangoRequest) -> Request:
    """
    Demote a DjangoRequest into a core Request.

    This is a thin wrapper over `simcore_ai_django.types.demote.demote_request` that
    preserves identity, provider/client, and returns a core Request with unchanged correlation id and codec hints.
    """
    with service_span_sync(
            "svc.demote_request_for_service",
            attributes=_span_attrs_from_request(dj),
    ):
        return _dto_demote_request(dj)


def demote_response_for_service(dj: DjangoResponse) -> Response:
    """
    Demote a DjangoResponse into a core Response.

    This is a thin wrapper over `simcore_ai_django.types.demote.demote_response` that
    preserves identity, provider/client metadata, and `received_at`, returning a core Response.
    """
    with service_span_sync(
            "svc.demote_response_for_service",
            attributes=_span_attrs_from_response(dj),
    ):
        return _dto_demote_response(dj)


__all__ = [
    "demote_request_for_service",
    "demote_response_for_service",
]
