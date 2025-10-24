# simcore_ai_django/signals.py
"""Django signals for simcore_ai_django glue.

Provides typed payload contracts (TypedDict) for clarity and forwards-compatibility.
"""

from typing import TypedDict, Optional
from uuid import UUID

from django.dispatch import Signal


class RequestSentPayload(TypedDict, total=False):
    request: dict
    request_audit_pk: Optional[int]
    namespace: Optional[str]
    namespace: Optional[str]
    kind: Optional[str]
    service_name: Optional[str]
    client_name: Optional[str]
    provider_name: Optional[str]
    simulation_pk: Optional[int]
    correlation_id: Optional[UUID]
    codec_name: Optional[str]


class ResponseReceivedPayload(TypedDict, total=False):
    response: dict
    response_audit_pk: Optional[int]
    request_audit_pk: Optional[int]
    namespace: Optional[str]
    namespace: Optional[str]
    kind: Optional[str]
    service_name: Optional[str]
    client_name: Optional[str]
    provider_name: Optional[str]
    simulation_pk: Optional[int]
    correlation_id: Optional[UUID]
    codec_name: Optional[str]


class ResponseReadyPayload(TypedDict, total=False):
    response: dict
    response_audit_pk: Optional[int]
    request_audit_pk: Optional[int]
    namespace: Optional[str]
    namespace: Optional[str]
    kind: Optional[str]
    service_name: Optional[str]
    client_name: Optional[str]
    provider_name: Optional[str]
    simulation_pk: Optional[int]
    correlation_id: Optional[UUID]
    codec_name: Optional[str]


class ResponseFailedPayload(TypedDict, total=False):
    error: str
    request_audit_pk: Optional[int]
    namespace: Optional[str]
    namespace: Optional[str]
    kind: Optional[str]
    service_name: Optional[str]
    client_name: Optional[str]
    provider_name: Optional[str]
    simulation_pk: Optional[int]
    correlation_id: Optional[UUID]


class OutboxDispatchPayload(TypedDict, total=False):
    message: dict
    namespace: Optional[str]
    simulation_pk: Optional[int]


ai_request_sent = Signal()
ai_response_received = Signal()
ai_response_ready = Signal()
ai_response_failed = Signal()
ai_outbox_dispatch = Signal()

# -----------------------------------------------------------------------------
# Default emitter that forwards events to Django signals
# -----------------------------------------------------------------------------
class DjangoSignalEmitter:
    """Lightweight emitter that forwards events to Django signals via send_robust."""

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

# shared instance used by default in DjangoBaseLLMService
emitter = DjangoSignalEmitter()

__all__ = [
    # payload contracts
    "RequestSentPayload",
    "ResponseReceivedPayload",
    "ResponseReadyPayload",
    "ResponseFailedPayload",
    "OutboxDispatchPayload",
    # signals
    "ai_request_sent",
    "ai_response_received",
    "ai_response_ready",
    "ai_response_failed",
    "ai_outbox_dispatch",
    "emitter",
]
