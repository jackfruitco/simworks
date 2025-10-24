from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from django.db import transaction

from .signals import (
    ai_request_sent,
    ai_response_received,
    ai_response_ready,
    ai_response_failed,
)

logger = logging.getLogger(__name__)


# --- New, namespace-based emitters --------------------------------------

def emit_request(*, request_dto, namespace: Optional[str] = None, client_name: Optional[str] = None,
                 provider_name: Optional[str] = None, simulation_pk: Optional[int] = None,
                 correlation_id: Optional[UUID] = None, codec_name: Optional[str] = None,
                 request_audit_pk: Optional[int] = None, namespace: Optional[str] = None,
                 kind: Optional[str] = None, service_name: Optional[str] = None) -> None:
    payload = dict(
        request=request_dto,
        request_audit_pk=request_audit_pk,
        namespace=namespace,
        namespace=namespace,
        kind=kind,
        service_name=service_name,
        client_name=client_name,
        provider_name=provider_name,
        simulation_pk=simulation_pk,
        correlation_id=correlation_id,
        codec_name=codec_name,
    )
    logger.debug("emit_request: namespace=%s client=%s provider=%s corr=%s", namespace, client_name, provider_name,
                 correlation_id)
    transaction.on_commit(lambda: ai_request_sent.send_robust(sender=None, **payload))


def emit_response_received(*, response_dto, namespace: Optional[str] = None, client_name: Optional[str] = None,
                           provider_name: Optional[str] = None, simulation_pk: Optional[int] = None,
                           correlation_id: Optional[UUID] = None, codec_name: Optional[str] = None,
                           response_audit_pk: Optional[int] = None, request_audit_pk: Optional[int] = None,
                           namespace: Optional[str] = None, kind: Optional[str] = None,
                           service_name: Optional[str] = None) -> None:
    payload = dict(
        response=response_dto,
        response_audit_pk=response_audit_pk,
        request_audit_pk=request_audit_pk,
        namespace=namespace,
        namespace=namespace,
        kind=kind,
        service_name=service_name,
        client_name=client_name,
        provider_name=provider_name,
        simulation_pk=simulation_pk,
        correlation_id=correlation_id,
        codec_name=codec_name,
    )
    logger.debug("emit_response_received: namespace=%s client=%s provider=%s corr=%s", namespace, client_name,
                 provider_name, correlation_id)
    transaction.on_commit(lambda: ai_response_received.send_robust(sender=None, **payload))


def emit_response_ready(*, response_dto, namespace: Optional[str] = None, client_name: Optional[str] = None,
                        provider_name: Optional[str] = None, simulation_pk: Optional[int] = None,
                        correlation_id: Optional[UUID] = None, codec_name: Optional[str] = None,
                        response_audit_pk: Optional[int] = None, request_audit_pk: Optional[int] = None,
                        namespace: Optional[str] = None, kind: Optional[str] = None,
                        service_name: Optional[str] = None) -> None:
    payload = dict(
        response=response_dto,
        response_audit_pk=response_audit_pk,
        request_audit_pk=request_audit_pk,
        namespace=namespace,
        namespace=namespace,
        kind=kind,
        service_name=service_name,
        client_name=client_name,
        provider_name=provider_name,
        simulation_pk=simulation_pk,
        correlation_id=correlation_id,
        codec_name=codec_name,
    )
    logger.debug("emit_response_ready: namespace=%s client=%s provider=%s corr=%s", namespace, client_name,
                 provider_name, correlation_id)
    transaction.on_commit(lambda: ai_response_ready.send_robust(sender=None, **payload))


def emit_failure(*, error: str, namespace: Optional[str] = None, client_name: Optional[str] = None,
                 provider_name: Optional[str] = None, simulation_pk: Optional[int] = None,
                 correlation_id: Optional[UUID] = None, request_audit_pk: Optional[int] = None,
                 namespace: Optional[str] = None, kind: Optional[str] = None,
                 service_name: Optional[str] = None) -> None:
    payload = dict(
        error=error,
        request_audit_pk=request_audit_pk,
        namespace=namespace,
        namespace=namespace,
        kind=kind,
        service_name=service_name,
        client_name=client_name,
        provider_name=provider_name,
        simulation_pk=simulation_pk,
        correlation_id=correlation_id,
    )
    logger.debug("emit_failure: namespace=%s client=%s provider=%s corr=%s", namespace, client_name, provider_name,
                 correlation_id)
    transaction.on_commit(lambda: ai_response_failed.send_robust(sender=None, **payload))
