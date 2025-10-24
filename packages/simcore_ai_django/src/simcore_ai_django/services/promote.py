# simcore_ai_django/services/promote.py
from __future__ import annotations

"""
Service-level promotion helpers.

These helpers promote core `simcore_ai` request/response models into Django DTOs,
enriching them with service-derived identity (namespace/kind/name), provider/client
metadata, and optional database PKs. They build on the lower-level DTO helpers in
`simcore_ai_django.types.promote`.
"""

from typing import Any, Optional, Tuple
from uuid import UUID

from simcore_ai.types import LLMRequest, LLMResponse
from simcore_ai_django.types import (
    DjangoLLMRequest,
    DjangoLLMResponse,
)
from simcore_ai_django.types.promote import (
    promote_request as _dto_promote_request,
    promote_response as _dto_promote_response,
)
from simcore_ai.tracing import service_span_sync


def _extract_provider_client(service: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Best-effort extraction of provider/client names from a DjangoBaseLLMService instance.
    Both values are optional; absence is acceptable for environments that don't register
    provider/client metadata.
    """
    provider_name: Optional[str] = None
    client_name: Optional[str] = None

    # Preferred: explicit attributes on the service
    provider_name = getattr(service, "provider_name", None) or getattr(service, "provider", None)
    client_name = getattr(service, "client_name", None) or getattr(service, "client_id", None)

    # Fallback: inspect a bound client object if present
    client_obj = getattr(service, "client", None)
    if client_obj is not None:
        # Common names used across provider/client implementations
        provider_name = getattr(client_obj, "provider", None) or getattr(client_obj, "provider_name", provider_name)
        client_name = getattr(client_obj, "name", None) or getattr(client_obj, "client_name", client_name)

    # Coerce to strings if non-None
    if provider_name is not None:
        provider_name = str(provider_name)
    if client_name is not None:
        client_name = str(client_name)

    return provider_name, client_name


def promote_request_for_service(
        service: Any,
        req: LLMRequest,
        *,
        simulation_pk: int | UUID | None = None,
        request_db_pk: int | UUID | None = None,
) -> DjangoLLMRequest:
    """
    Promote a core LLMRequest into a DjangoLLMRequest, enriched with identity and metadata
    derived from the given service.

    Identity comes from the service attributes: `namespace`, `kind`, `name`.
    Provider/client metadata is attached when available.

    Args:
        service: The DjangoBaseLLMService (or compatible) instance.
        req: Core LLMRequest to promote.
        simulation_pk: Optional Simulation primary key (int or UUID).
        request_db_pk: Optional DB PK for the request row (int or UUID).

    Returns:
        DjangoLLMRequest populated with rich `messages_rich` and metadata.
    """
    with service_span_sync(
        "svc.promote_request_for_service",
        attributes={
            "svc.class": service.__class__.__name__,
            "svc.namespace": getattr(service, "namespace", None),
            "svc.kind": getattr(service, "kind", None),
            "svc.name": getattr(service, "name", None),
            "svc.provider": getattr(service, "provider_name", None) or getattr(getattr(service, "client", None), "provider", None),
            "svc.client": getattr(service, "client_name", None) or getattr(getattr(service, "client", None), "name", None),
            "req.correlation_id": getattr(req, "correlation_id", None),
            "db.simulation_pk": str(simulation_pk) if simulation_pk is not None else None,
            "db.request_pk": str(request_db_pk) if request_db_pk is not None else None,
        },
    ):
        # Build the base Django DTO, letting the DTO promotion helper enrich messages_rich.
        dj = DjangoLLMRequest(
            correlation_id=getattr(req, "correlation_id", None),
            namespace=getattr(service, "namespace", None),
            kind=getattr(service, "kind", None),
            name=getattr(service, "name", None),
            provider_name=_extract_provider_client(service)[0],
            client_name=_extract_provider_client(service)[1],
            simulation_pk=simulation_pk,
            db_pk=request_db_pk,
        )

        # Promote messages into rich overlay; also propagate request correlation id to sub-objects.
        _dto_promote_request(
            req,
            dj,
        )

        # Provide the request_correlation_id to rich message rows if available.
        req_corr = getattr(req, "correlation_id", None)
        try:
            from simcore_ai_django.types.promote import _promote_messages as _pm  # type: ignore
            _pm(  # type: ignore
                req,
                dj,
                request_db_pk=dj.db_pk,
                request_correlation_id=req_corr,
            )
        except Exception:
            pass

        return dj


def promote_response_for_service(
        service: Any,
        resp: LLMResponse,
        *,
        simulation_pk: int | UUID | None = None,
        request_db_pk: int | UUID | None = None,
        response_db_pk: int | UUID | None = None,
) -> DjangoLLMResponse:
    """
    Promote a core LLMResponse into a DjangoLLMResponse, enriched with identity and metadata
    derived from the given service.

    Identity comes from the service attributes: `namespace`, `kind`, `name`.
    Provider/client metadata is attached when available.

    Args:
        service: The DjangoBaseLLMService (or compatible) instance.
        resp: Core LLMResponse to promote.
        simulation_pk: Optional Simulation primary key (int or UUID).
        request_db_pk: Optional DB PK for the originating request (int or UUID).
        response_db_pk: Optional DB PK for this response (int or UUID).

    Returns:
        DjangoLLMResponse populated with rich `outputs_rich`/`usage_rich` and metadata.
    """
    prov, cli = _extract_provider_client(service)
    with service_span_sync(
        "svc.promote_response_for_service",
        attributes={
            "svc.class": service.__class__.__name__,
            "svc.namespace": getattr(service, "namespace", None),
            "svc.kind": getattr(service, "kind", None),
            "svc.name": getattr(service, "name", None),
            "svc.provider": prov,
            "svc.client": cli,
            "resp.correlation_id": getattr(resp, "correlation_id", None),
            "resp.request_correlation_id": getattr(resp, "request_correlation_id", None),
            "db.simulation_pk": str(simulation_pk) if simulation_pk is not None else None,
            "db.request_pk": str(request_db_pk) if request_db_pk is not None else None,
            "db.response_pk": str(response_db_pk) if response_db_pk is not None else None,
        },
    ):
        dj = DjangoLLMResponse(
            correlation_id=getattr(resp, "correlation_id", None),
            request_correlation_id=getattr(resp, "request_correlation_id", None),
            namespace=getattr(service, "namespace", None),
            kind=getattr(service, "kind", None),
            name=getattr(service, "name", None),
            provider_name=prov,
            client_name=cli,
            received_at=getattr(resp, "received_at", None),
            simulation_pk=simulation_pk,
            request_db_pk=request_db_pk,
            db_pk=response_db_pk,
        )

        _dto_promote_response(resp, dj)

        req_corr = getattr(resp, "request_correlation_id", None)
        resp_corr = getattr(resp, "correlation_id", None)
        try:
            from simcore_ai_django.types.promote import _promote_response_items as _pri  # type: ignore
            from simcore_ai_django.types.promote import _promote_usage as _pu  # type: ignore
            _pri(  # type: ignore
                resp,
                dj,
                response_db_pk=response_db_pk,
                request_db_pk=request_db_pk,
                request_correlation_id=req_corr,
                response_correlation_id=resp_corr,
            )
            _pu(  # type: ignore
                resp,
                dj,
                response_db_pk=response_db_pk,
                request_correlation_id=req_corr,
                response_correlation_id=resp_corr,
            )
        except Exception:
            pass

        return dj
