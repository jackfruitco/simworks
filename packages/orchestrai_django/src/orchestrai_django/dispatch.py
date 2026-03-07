# orchestrai/dispatch.py


from functools import partial
import logging
from uuid import UUID

from asgiref.sync import sync_to_async  # NEW
from django.db import transaction

from .signals import (
    ai_request_sent,
    ai_response_failed,
    ai_response_ready,
    ai_response_received,
)

logger = logging.getLogger(__name__)


# --- helpers --------------------------------------------------------------


def _ident_label(namespace: str | None, kind: str | None, name: str | None) -> str:
    ns = namespace or "default"
    kd = kind or "default"
    nm = name or "default"
    return f"{ns}.{kd}.{nm}"


def _on_commit_send(signal, payload: dict) -> None:
    """
    Register a callback to send the given signal with payload after the
    current transaction commits. Sync-only helper.
    """
    callback = partial(signal.send_robust, sender=None, **payload)
    transaction.on_commit(callback)


async def _a_on_commit_send(signal, payload: dict) -> None:
    """
    Async-safe variant: registers the same callback in a thread-sensitive
    executor so Django's sync DB connection is used safely.
    Must be awaited to ensure registration happens before the atomic
    block exits.
    """
    callback = partial(signal.send_robust, sender=None, **payload)
    await sync_to_async(transaction.on_commit, thread_sensitive=True)(callback)


# --- Identity-first emitters (namespace, kind, name) --------------------


def emit_request(
    *,
    request_dto,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "request": request_dto,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "emit_request: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    _on_commit_send(ai_request_sent, payload)


async def aemit_request(  # NEW
    *,
    request_dto,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "request": request_dto,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "aemit_request: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    await _a_on_commit_send(ai_request_sent, payload)


def emit_response_received(
    *,
    response_dto,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    response_audit_pk: int | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "response": response_dto,
        "response_audit_pk": response_audit_pk,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "emit_response_received: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    _on_commit_send(ai_response_received, payload)


async def aemit_response_received(  # NEW
    *,
    response_dto,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    response_audit_pk: int | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "response": response_dto,
        "response_audit_pk": response_audit_pk,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "aemit_response_received: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    await _a_on_commit_send(ai_response_received, payload)


def emit_response_ready(
    *,
    response_dto,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    response_audit_pk: int | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "response": response_dto,
        "response_audit_pk": response_audit_pk,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "emit_response_ready: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    _on_commit_send(ai_response_ready, payload)


async def aemit_response_ready(  # NEW
    *,
    response_dto,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    response_audit_pk: int | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "response": response_dto,
        "response_audit_pk": response_audit_pk,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "aemit_response_ready: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    await _a_on_commit_send(ai_response_ready, payload)


def emit_failure(
    *,
    error: str,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "error": error,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "emit_failure: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    _on_commit_send(ai_response_failed, payload)


async def aemit_failure(  # NEW
    *,
    error: str,
    namespace: str | None = None,
    kind: str | None = None,
    name: str | None = None,
    client_name: str | None = None,
    provider_name: str | None = None,
    object_db_pk: int | UUID | None = None,
    context: dict | None = None,
    correlation_id: UUID | None = None,
    request_audit_pk: int | None = None,
) -> None:
    payload = {
        "error": error,
        "request_audit_pk": request_audit_pk,
        "namespace": namespace,
        "kind": kind,
        "name": name,
        "client_name": client_name,
        "provider_name": provider_name,
        "object_db_pk": object_db_pk,
        "context": context,
        "correlation_id": correlation_id,
    }
    logger.debug(
        "aemit_failure: ident=%s client=%s backend=%s corr=%s",
        _ident_label(namespace, kind, name),
        client_name,
        provider_name,
        correlation_id,
    )
    await _a_on_commit_send(ai_response_failed, payload)
