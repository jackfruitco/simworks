# orchestrai_django/signals.py

from typing import Any, TypedDict
from uuid import UUID

from django.dispatch import Signal

from orchestrai_django.utils.serialization import pydantic_model_to_dict


def _as_dict(obj: Any) -> dict:
    """Best-effort conversion of Pydantic/dataclass objects to a dict for signal payloads."""
    return pydantic_model_to_dict(obj)


def _split_identity(identity: str) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Split an identity string like 'services.chatlab.standardized_patient.initial'
    into (domain, namespace, kind/group, service_name). Any missing pieces are None.
    """
    parts = (identity or "").split(".")
    domain = parts[0] if len(parts) > 0 else None
    namespace = parts[1] if len(parts) > 1 else None
    kind = parts[2] if len(parts) > 2 else None
    service_name = parts[3] if len(parts) > 3 else None
    return domain, namespace, kind, service_name


class RequestSentPayload(TypedDict, total=False):
    request: dict
    request_audit_pk: int | None
    domain: str | None
    namespace: str | None
    kind: str | None
    service_name: str | None
    client_name: str | None
    provider_name: str | None
    # DB linkage
    object_db_pk: int | UUID | None
    # Correlation
    correlation_id: UUID | None
    # Context-first
    context: dict[str, Any] | None


class ResponseReceivedPayload(TypedDict, total=False):
    response: dict
    response_audit_pk: int | None
    request_audit_pk: int | None
    domain: str | None
    namespace: str | None
    kind: str | None
    service_name: str | None
    client_name: str | None
    provider_name: str | None
    # Optional generic DB linkage
    object_db_pk: int | UUID | None
    # Correlation
    correlation_id: UUID | None
    # Context-first
    context: dict[str, Any] | None


class ResponseReadyPayload(TypedDict, total=False):
    response: dict
    response_audit_pk: int | None
    request_audit_pk: int | None
    domain: str | None
    namespace: str | None
    kind: str | None
    service_name: str | None
    client_name: str | None
    provider_name: str | None
    # Generic DB linkage (preferred) + legacy name for back-compat
    object_db_pk: int | UUID | None
    # Correlation
    correlation_id: UUID | None
    # Context-first
    context: dict[str, Any] | None


class ResponseFailedPayload(TypedDict, total=False):
    error: str
    request_audit_pk: int | None
    domain: str | None
    namespace: str | None
    kind: str | None
    service_name: str | None
    client_name: str | None
    provider_name: str | None
    # Generic DB linkage (preferred) + legacy name for back-compat
    object_db_pk: int | UUID | None
    # Correlation
    correlation_id: UUID | None
    # Context-first
    context: dict[str, Any] | None


class OutboxDispatchPayload(TypedDict, total=False):
    message: dict
    domain: str | None
    namespace: str | None
    # Generic DB linkage (preferred) + legacy name for back-compat
    object_db_pk: int | UUID | None
    # Context-first
    context: dict[str, Any] | None


ai_request_sent = Signal()
ai_response_received = Signal()
ai_response_ready = Signal()
ai_response_failed = Signal()
ai_outbox_dispatch = Signal()
domain_object_created = Signal()  # Emitted after persistence handler creates domain object


# -----------------------------------------------------------------------------
# Default emitter that forwards events to Django signals
# -----------------------------------------------------------------------------
class DjangoSignalEmitter:
    """Lightweight emitter that forwards events to Django signals via send_robust.

    This class is also compatible with orchestrai.components.services.ServiceEmitter:
    it exposes `emit_request`, `emit_response`, `emit_failure`,
    `emit_stream_chunk`, and `emit_stream_complete`, which are the methods
    BaseService/ DjangoBaseService expect.
    """

    # ---- Original public API (kept for back-compat) --------------------
    def request_sent(self, payload: RequestSentPayload) -> None:
        ai_request_sent.send_robust(sender=self.__class__, **payload)

    def response_received(self, payload: ResponseReceivedPayload) -> None:
        ai_response_received.send_robust(sender=self.__class__, **payload)

    def response_ready(self, payload: ResponseReadyPayload) -> None:
        ai_response_ready.send_robust(sender=self.__class__, **payload)

    def response_failed(self, payload: ResponseFailedPayload) -> None:
        # Ensure error is a string for robustness
        if "error" in payload and not isinstance(payload["error"], str):
            payload = dict(payload)
            payload["error"] = str(payload["error"])
        ai_response_failed.send_robust(sender=self.__class__, **payload)

    def outbox_dispatch(self, payload: OutboxDispatchPayload) -> None:
        ai_outbox_dispatch.send_robust(sender=self.__class__, **payload)

    # ---- ServiceEmitter-compatible API (used by BaseService) ----------

    def emit_request(self, context: dict, identity: str, request_dto: Any) -> None:
        """Adapter for BaseService→Django signals on request send."""
        domain, namespace, kind, service_name = _split_identity(identity)
        ctx = dict(context or {})
        payload: RequestSentPayload = {
            "request": _as_dict(request_dto),
            "domain": domain,
            "namespace": namespace,
            "kind": kind,
            "service_name": service_name,
            "correlation_id": getattr(request_dto, "correlation_id", None),
            "object_db_pk": ctx.get("object_db_pk"),
            "context": ctx,
        }
        self.request_sent(payload)

    def emit_response(self, context: dict, identity: str, response_dto: Any) -> None:
        """Adapter for BaseService→Django signals on final response."""
        domain, namespace, kind, service_name = _split_identity(identity)
        ctx = dict(context or {})
        payload: ResponseReadyPayload = {
            "response": _as_dict(response_dto),
            "domain": domain,
            "namespace": namespace,
            "kind": kind,
            "service_name": service_name,
            "correlation_id": getattr(response_dto, "request_correlation_id", None),
            "object_db_pk": ctx.get("object_db_pk"),
            "context": ctx,
        }
        # Treat as "ready" (post-decode, post-success) and also "received" for
        # consumers that only listen to the older signal.
        self.response_received(payload)  # type: ignore[arg-type]
        self.response_ready(payload)

    def emit_failure(self, context: dict, identity: str, correlation_id: Any, error: str) -> None:
        """Adapter for BaseService→Django signals on failure."""
        domain, namespace, kind, service_name = _split_identity(identity)
        ctx = dict(context or {})
        payload: ResponseFailedPayload = {
            "error": str(error),
            "domain": domain,
            "namespace": namespace,
            "kind": kind,
            "service_name": service_name,
            "correlation_id": correlation_id,
            "object_db_pk": ctx.get("object_db_pk"),
            "context": ctx,
        }
        self.response_failed(payload)

    def emit_stream_chunk(self, context: dict, identity: str, chunk_dto: Any) -> None:
        """Adapter for streaming chunks; forwarded via outbox_dispatch."""
        domain, namespace, _, _ = _split_identity(identity)
        ctx = dict(context or {})
        payload: OutboxDispatchPayload = {
            "message": _as_dict(chunk_dto),
            "domain": domain,
            "namespace": namespace,
            "object_db_pk": ctx.get("object_db_pk"),
            "context": ctx,
        }
        self.outbox_dispatch(payload)

    def emit_stream_complete(self, context: dict, identity: str, correlation_id: Any) -> None:
        """Adapter for stream completion; currently a no-op hook."""
        # You can optionally send a final "stream complete" outbox message here
        # if you want consumers to know the stream is closed.
        return None


# shared instance used by default in DjangoBaseService
emitter = DjangoSignalEmitter()

__all__ = [
    "OutboxDispatchPayload",
    # payload contracts
    "RequestSentPayload",
    "ResponseFailedPayload",
    "ResponseReadyPayload",
    "ResponseReceivedPayload",
    "ai_outbox_dispatch",
    # signals
    "ai_request_sent",
    "ai_response_failed",
    "ai_response_ready",
    "ai_response_received",
    "domain_object_created",
    "emitter",
]
