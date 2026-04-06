from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any
import uuid

from apps.common.outbox import event_types as outbox_events

SESSION_HELLO = "session.hello"
SESSION_RESUME = "session.resume"
TYPING_STARTED = "typing.started"
TYPING_STOPPED = "typing.stopped"
PING = "ping"

SESSION_READY = "session.ready"
SESSION_RESUMED = "session.resumed"
SESSION_RESYNC_REQUIRED = "session.resync_required"
ERROR = "error"
PONG = "pong"

ALLOWED_INBOUND_EVENT_TYPES = frozenset(
    {
        SESSION_HELLO,
        SESSION_RESUME,
        TYPING_STARTED,
        TYPING_STOPPED,
        PING,
    }
)
TRANSIENT_EVENT_TYPES = frozenset(
    {
        SESSION_READY,
        SESSION_RESUMED,
        SESSION_RESYNC_REQUIRED,
        ERROR,
        PONG,
        TYPING_STARTED,
        TYPING_STOPPED,
    }
)
DURABLE_EVENT_TYPES = frozenset(outbox_events.canonical_event_types())


@dataclass(slots=True, frozen=True)
class ParsedInboundMessage:
    event_type: str
    payload: dict[str, Any]
    correlation_id: str | None = None


class InboundMessageError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def is_durable_event_type(event_type: str) -> bool:
    return event_type in DURABLE_EVENT_TYPES


def is_transient_event_type(event_type: str) -> bool:
    return event_type in TRANSIENT_EVENT_TYPES


def build_realtime_envelope(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
    event_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "correlation_id": correlation_id,
        "payload": payload or {},
    }


def build_error_envelope(
    *,
    code: str,
    message: str,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return build_realtime_envelope(
        ERROR,
        payload,
        correlation_id=correlation_id,
    )


def envelope_sort_key(envelope: dict[str, Any]) -> tuple[str, str]:
    return (
        str(envelope.get("created_at") or ""),
        str(envelope.get("event_id") or ""),
    )


def merge_envelopes_in_order(*envelope_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for envelope in sorted(
        [envelope for batch in envelope_lists for envelope in batch],
        key=envelope_sort_key,
    ):
        event_id = str(envelope.get("event_id") or "")
        if not event_id or event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        merged.append(envelope)
    return merged


def normalize_last_event_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InboundMessageError(
            "invalid_last_event_id",
            "last_event_id must be a string when provided",
        )
    trimmed = value.strip()
    if not trimmed:
        raise InboundMessageError(
            "invalid_last_event_id",
            "last_event_id must not be empty",
        )
    return trimmed


def parse_event_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise InboundMessageError(
            "invalid_last_event_id",
            "last_event_id must be a valid UUID",
        ) from exc


def _require_int(payload: dict[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or value <= 0:
        raise InboundMessageError(
            "invalid_payload",
            f"{field_name} must be a positive integer",
            details={"field": field_name},
        )
    return value


def _optional_int(payload: dict[str, Any], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise InboundMessageError(
            "invalid_payload",
            f"{field_name} must be a positive integer when provided",
            details={"field": field_name},
        )
    return value


def _validate_payload_keys(
    payload: dict[str, Any],
    *,
    allowed_keys: set[str],
) -> None:
    extra_keys = sorted(set(payload.keys()) - allowed_keys)
    if extra_keys:
        raise InboundMessageError(
            "invalid_payload",
            "payload contains unsupported fields",
            details={"extra_keys": extra_keys},
        )


def parse_inbound_message(text_data: str | None) -> ParsedInboundMessage:
    try:
        data = json.loads(text_data or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise InboundMessageError(
            "invalid_json",
            "Inbound WebSocket message must be valid JSON",
        ) from exc

    if not isinstance(data, dict):
        raise InboundMessageError(
            "invalid_shape",
            "Inbound WebSocket message must be an object",
        )

    allowed_keys = {"event_type", "correlation_id", "payload"}
    extra_keys = sorted(set(data.keys()) - allowed_keys)
    if extra_keys:
        raise InboundMessageError(
            "invalid_shape",
            "Inbound WebSocket message contains unsupported top-level fields",
            details={"extra_keys": extra_keys},
        )

    event_type = data.get("event_type")
    if not isinstance(event_type, str) or event_type not in ALLOWED_INBOUND_EVENT_TYPES:
        raise InboundMessageError(
            "unsupported_event_type",
            "Inbound WebSocket event_type is not supported",
            details={"event_type": event_type},
        )

    correlation_id = data.get("correlation_id")
    if correlation_id is not None and not isinstance(correlation_id, str):
        raise InboundMessageError(
            "invalid_correlation_id",
            "correlation_id must be a string when provided",
        )

    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise InboundMessageError(
            "invalid_payload",
            "payload must be a JSON object",
        )

    if event_type == SESSION_HELLO:
        _validate_payload_keys(payload, allowed_keys={"simulation_id", "last_event_id"})
        _require_int(payload, "simulation_id")
        normalize_last_event_id(payload.get("last_event_id"))
    elif event_type == SESSION_RESUME:
        _validate_payload_keys(payload, allowed_keys={"simulation_id", "last_event_id"})
        _require_int(payload, "simulation_id")
        if "last_event_id" not in payload:
            raise InboundMessageError(
                "invalid_payload",
                "session.resume requires last_event_id",
                details={"field": "last_event_id"},
            )
        normalize_last_event_id(payload.get("last_event_id"))
    elif event_type in {TYPING_STARTED, TYPING_STOPPED}:
        _validate_payload_keys(payload, allowed_keys={"conversation_id"})
        _optional_int(payload, "conversation_id")
    elif event_type == PING:
        _validate_payload_keys(payload, allowed_keys={"client_timestamp", "client_nonce"})

    return ParsedInboundMessage(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id.strip() if isinstance(correlation_id, str) else None,
    )
