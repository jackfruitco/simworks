# orchestrai_django/services/promote.py


"""
Service-level promotion helpers (Django layer).

These helpers promote core `orchestrai` request/response models into Django DTOs,
enriching them with **service-derived identity** (namespace/kind/name), backend/client
metadata, and optional database PKs. They build on the lower-level DTO helpers in
`orchestrai_django.types.promote`.

Identity is resolved **upstream** (decorators / identity resolvers). This module assumes
`service.identity` is an `Identity` instance and does **not** perform token stripping or
normalization. When `service.identity` is unavailable, we make a best-effort fallback to
`service.namespace/kind/name` without mutating the service.
"""

from typing import Any, Optional
from uuid import UUID

from orchestrai.types import Request, Response
from orchestrai.tracing import service_span_sync
from orchestrai.identity import Identity

from orchestrai_django.types import (
    DjangoRequest,
    DjangoResponse,
)
from orchestrai_django.types.promote import (
    promote_request as _dto_promote_request,
    promote_response as _dto_promote_response,
)

__all__ = ["promote_request_for_service", "promote_response_for_service"]


# ---------------------------------------------------------------------------
# identity helpers
# ---------------------------------------------------------------------------

def _svc_identity_str(service: Any) -> Optional[str]:
    """Return canonical `namespace.kind.name` string for a service if available."""
    ident: Optional[Identity] = getattr(service, "identity", None)
    if isinstance(ident, Identity) and all((ident.namespace, ident.kind, ident.name)):
        return ident.as_str
    ns = getattr(service, "namespace", None)
    kd = getattr(service, "kind", None)
    nm = getattr(service, "name", None)
    if ns and kd and nm:
        return f"{ns}.{kd}.{nm}"
    return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _svc_identity_tuple3(service: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (namespace, kind, name) for a service, preferring `service.identity`.

    We *do not* mutate the service or synthesize an Identity. This is a read-only
    extraction for tracing/DTO enrichment.
    """
    ident: Optional[Identity] = getattr(service, "identity", None)
    if isinstance(ident, Identity):
        ns, kd, nm = ident.namespace, ident.kind, ident.name
        return ns, kd, nm
    # best-effort fallbacks for legacy callers
    ns = getattr(service, "namespace", None)
    kd = getattr(service, "kind", None)
    nm = getattr(service, "name", None)
    return ns, kd, nm


def _extract_provider_client(service: Any) -> tuple[Optional[str], Optional[str]]:
    """Best-effort extraction of backend/client names from a service instance.

    Both values are optional; absence is acceptable for environments that don't register
    backend/client metadata.
    """
    provider_name: Optional[str] = getattr(service, "provider_name", None) or getattr(service, "backend", None)
    client_name: Optional[str] = getattr(service, "client_name", None) or getattr(service, "client_id", None)

    # Fallback: inspect a bound client object if present
    client_obj = getattr(service, "client", None)
    if client_obj is not None:
        provider_name = getattr(client_obj, "backend", None) or getattr(client_obj, "provider_name", provider_name)
        client_name = getattr(client_obj, "name", None) or getattr(client_obj, "client_name", client_name)

    # Coerce to strings if non-None
    if provider_name is not None:
        provider_name = str(provider_name)
    if client_name is not None:
        client_name = str(client_name)

    return provider_name, client_name


# ---------------------------------------------------------------------------
# promotions
# ---------------------------------------------------------------------------

def promote_request_for_service(
        service: Any,
        req: Request,
        *,
        context: dict | None = None,
) -> DjangoRequest:
    """Promote a core Request into a DjangoRequest with identity + metadata.

    Identity comes from `service.identity` (preferred) or legacy `namespace/kind/name`.
    Identities are expected to be already normalized (dot-only triples) upstream.
    This function does not perform token stripping or normalization.

    Parameters
    ----------
    service: DjangoBaseService (or compatible) instance.
    req: Core Request to promote.
    context: Optional extra context to carry through the promotion pipeline.

    Returns
    -------
    DjangoRequest populated with rich `messages_rich` and metadata.
    """
    ns, kd, nm = _svc_identity_tuple3(service)
    prov, cli = _extract_provider_client(service)

    with service_span_sync(
            "svc.promote_request_for_service",
            attributes={
                "svc.class": service.__class__.__name__,
                "orchestrai.identity.service": _svc_identity_str(service),
                "orchestrai.identity.service.tuple3": (ns, kd, nm) if all([ns, kd, nm]) else None,
                "svc.backend": prov,
                "svc.client": cli,
                "req.correlation_id": getattr(req, "correlation_id", None),
                **getattr(service, "flatten_context", lambda: {})(),
            },
    ):
        dj = _dto_promote_request(
            req,
            correlation_id=getattr(req, "correlation_id", None),
            namespace=ns,
            kind=kd,
            name=nm,
            provider_name=prov,
            client_name=cli,
            context=context,
        )
        return dj


def promote_response_for_service(
        service: Any,
        resp: Response,
        *,
        object_db_pk: int | UUID | None = None,
        request_db_pk: int | UUID | None = None,
        response_db_pk: int | UUID | None = None,
) -> DjangoResponse:
    """Promote a core Response into a DjangoResponse with identity + metadata.

    Identity comes from `service.identity` (preferred) or legacy `namespace/kind/name`.
    Identities are expected to be already normalized (dot-only triples) upstream.
    This function does not perform token stripping or normalization.

    Parameters
    ----------
    service: DjangoBaseService (or compatible) instance.
    resp: Core Response to promote.
    object_db_pk: Optional Simulation primary key (int or UUID).
    request_db_pk: Optional DB PK for the originating request (int or UUID).
    response_db_pk: Optional DB PK for this response (int or UUID).

    Returns
    -------
    DjangoResponse populated with rich `outputs_rich`/`usage_rich` and metadata.
    """
    ns, kd, nm = _svc_identity_tuple3(service)
    prov, cli = _extract_provider_client(service)

    with service_span_sync(
            "svc.promote_response_for_service",
            attributes={
                "svc.class": service.__class__.__name__,
                "orchestrai.identity.service": _svc_identity_str(service),
                "orchestrai.identity.service.tuple3": (ns, kd, nm) if all([ns, kd, nm]) else None,
                "svc.backend": prov,
                "svc.client": cli,
                "resp.correlation_id": getattr(resp, "correlation_id", None),
                "resp.request_correlation_id": getattr(resp, "request_correlation_id", None),
                "db.object_db_pk": str(object_db_pk) if object_db_pk is not None else None,
                "db.request_pk": str(request_db_pk) if request_db_pk is not None else None,
                "db.response_pk": str(response_db_pk) if response_db_pk is not None else None,
                **getattr(service, "flatten_context", lambda: {})(),
            },
    ):
        dj = _dto_promote_response(
            resp,
            correlation_id=getattr(resp, "correlation_id", None),
            request_correlation_id=getattr(resp, "request_correlation_id", None),
            namespace=ns,
            kind=kd,
            name=nm,
            provider_name=prov,
            client_name=cli,
            received_at=getattr(resp, "received_at", None),
            object_db_pk=object_db_pk,
            request_db_pk=request_db_pk,
            db_pk=response_db_pk,
        )
        return dj
