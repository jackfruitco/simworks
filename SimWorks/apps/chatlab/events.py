"""ChatLab-owned event serialization and emit helpers."""

from __future__ import annotations

from datetime import UTC
import hashlib
from typing import Any

from .media_payloads import build_chat_message_event_payload, payload_message_id


def _metadata_kind(meta) -> str:
    model_name = getattr(getattr(meta, "_meta", None), "model_name", "") or ""
    kind_by_model = {
        "labresult": "lab_result",
        "radresult": "rad_result",
        "patienthistory": "patient_history",
        "patientdemographics": "patient_demographics",
        "simulationfeedback": "simulation_feedback",
        "simulationmetadata": "generic",
    }
    if model_name in kind_by_model:
        return kind_by_model[model_name]

    class_name = meta.__class__.__name__.lower()
    return kind_by_model.get(class_name, "generic")


def build_metadata_created_payload(meta) -> dict[str, Any]:
    """Build the legacy per-row metadata payload shape."""
    return {
        "metadata_id": meta.id,
        "kind": _metadata_kind(meta),
        "key": meta.key,
        "value": meta.value,
    }


def _metadata_version_token(meta) -> str:
    timestamp = getattr(meta, "modified_at", None) or getattr(meta, "created_at", None)
    if timestamp is None:
        return str(meta.id)
    return str(int(timestamp.timestamp() * 1_000_000))


def metadata_outbox_idempotency_key(event_type: str, meta) -> str:
    """Build an idempotency key that changes when a metadata row is updated."""
    model_label = type(meta).__name__
    version_token = _metadata_version_token(meta)
    return f"{event_type}:{model_label}:{meta.id}:{version_token}"


def emit_chat_message_created_sync(
    message,
    *,
    correlation_id: str | None = None,
    status: str | None = None,
    fallback_conversation_type: str | None = None,
) -> bool:
    """Persist a durable ``chat.message_created`` event for a ChatLab message."""
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    event = enqueue_event_sync(
        event_type="chat.message_created",
        simulation_id=message.simulation_id,
        payload=build_chat_message_event_payload(
            message,
            status=status,
            fallback_conversation_type=fallback_conversation_type,
        ),
        idempotency_key=f"chat.message_created:{message.id}",
        correlation_id=correlation_id,
    )
    if event:
        poke_drain_sync()
    return event is not None


def emit_legacy_metadata_created_sync(
    metadata_items: list[Any],
    *,
    correlation_id: str | None = None,
) -> int:
    """Emit the legacy ChatLab ``metadata.created`` compatibility alias."""
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    emitted = 0
    for meta in metadata_items:
        event = enqueue_event_sync(
            event_type="metadata.created",
            simulation_id=meta.simulation_id,
            payload=build_metadata_created_payload(meta),
            idempotency_key=metadata_outbox_idempotency_key("metadata.created", meta),
            correlation_id=correlation_id,
        )
        if event:
            emitted += 1

    if emitted:
        poke_drain_sync()
    return emitted


def serialize_chatlab_event_payload(
    event,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Return the canonical ChatLab payload for an outbox event."""
    payload = dict(event.payload or {})
    if event.event_type != "chat.message_created":
        return payload

    message_id = payload_message_id(payload)
    if message_id is None:
        payload.setdefault("media_list", [])
        payload.setdefault("mediaList", [])
        return payload

    from .models import Message

    message = (
        Message.objects.select_related("conversation__conversation_type")
        .prefetch_related("media")
        .filter(id=message_id, simulation_id=event.simulation_id)
        .first()
    )
    if message is None:
        payload.setdefault("media_list", [])
        payload.setdefault("mediaList", [])
        return payload

    canonical = build_chat_message_event_payload(
        message,
        request=request,
        scheme=scheme,
        host=host,
        fallback_conversation_type=payload.get("conversation_type"),
        status=payload.get("status"),
    )

    merged = dict(payload)
    for key, value in canonical.items():
        if key in {"media_list", "mediaList"}:
            merged[key] = value
            continue
        if key not in merged or merged[key] in (None, ""):
            merged[key] = value

    merged.setdefault("media_list", [])
    merged.setdefault("mediaList", [])
    return merged


def build_chatlab_event_envelope(
    event,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Build the ChatLab transport envelope for WebSocket/SSE/catch-up."""
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "created_at": event.created_at,
        "correlation_id": event.correlation_id,
        "payload": serialize_chatlab_event_payload(
            event,
            request=request,
            scheme=scheme,
            host=host,
        ),
    }


def build_chatlab_transport_envelope(
    event,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe ChatLab transport envelope."""
    envelope = build_chatlab_event_envelope(
        event,
        request=request,
        scheme=scheme,
        host=host,
    )
    envelope["created_at"] = (
        event.created_at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    return envelope


def results_event_version_digest(results: list[Any], *, status: str | None = None) -> str:
    """Build a compact version digest for aggregated metadata result events."""
    parts = []
    for result in sorted(results, key=lambda item: item.id):
        parts.append(f"{result.id}:{_metadata_version_token(result)}")
    if status:
        parts.append(f"status:{status}")
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
