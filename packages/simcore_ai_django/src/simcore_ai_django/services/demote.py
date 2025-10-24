# simcore_ai_django/services/demote.py
from __future__ import annotations

"""
Service-level demotion helpers.

These helpers demote Django DTOs back into core `simcore_ai` request/response
models. They intentionally *preserve* identity (namespace/kind/name),
provider/client metadata, and `received_at` on responses, aligning with the
core model decisions.
"""

from simcore_ai.types import LLMRequest, LLMResponse
from simcore_ai_django.types.demote import (
    demote_request as _dto_demote_request,
    demote_response as _dto_demote_response,
)
from simcore_ai_django.types import DjangoLLMRequest, DjangoLLMResponse
from simcore_ai.tracing import service_span_sync


def demote_request_for_service(dj: DjangoLLMRequest) -> LLMRequest:
    """
    Demote a DjangoLLMRequest into a core LLMRequest.

    This is a thin wrapper over `simcore_ai_django.types.demote.demote_request` that
    preserves identity and metadata already carried by the Django DTO.
    """
    with service_span_sync(
        "svc.demote_request_for_service",
        attributes={
            "dj.correlation_id": getattr(dj, "correlation_id", None),
            "dj.namespace": getattr(dj, "namespace", None),
            "dj.kind": getattr(dj, "kind", None),
            "dj.name": getattr(dj, "name", None),
            "dj.provider": getattr(dj, "provider_name", None),
            "dj.client": getattr(dj, "client_name", None),
            "db.simulation_pk": str(getattr(dj, "simulation_pk", None)) if getattr(dj, "simulation_pk", None) is not None else None,
            "db.request_pk": str(getattr(dj, "db_pk", None)) if getattr(dj, "db_pk", None) is not None else None,
        },
    ):
        return _dto_demote_request(dj)


def demote_response_for_service(dj: DjangoLLMResponse) -> LLMResponse:
    """
    Demote a DjangoLLMResponse into a core LLMResponse.

    This is a thin wrapper over `simcore_ai_django.types.demote.demote_response` that
    preserves identity, provider/client metadata, and `received_at` per core decisions.
    """
    with service_span_sync(
        "svc.demote_response_for_service",
        attributes={
            "dj.correlation_id": getattr(dj, "correlation_id", None),
            "dj.request_correlation_id": getattr(dj, "request_correlation_id", None),
            "dj.namespace": getattr(dj, "namespace", None),
            "dj.kind": getattr(dj, "kind", None),
            "dj.name": getattr(dj, "name", None),
            "dj.provider": getattr(dj, "provider_name", None),
            "dj.client": getattr(dj, "client_name", None),
            "db.simulation_pk": str(getattr(dj, "simulation_pk", None)) if getattr(dj, "simulation_pk", None) is not None else None,
            "db.request_pk": str(getattr(dj, "request_db_pk", None)) if getattr(dj, "request_db_pk", None) is not None else None,
            "db.response_pk": str(getattr(dj, "db_pk", None)) if getattr(dj, "db_pk", None) is not None else None,
        },
    ):
        return _dto_demote_response(dj)
