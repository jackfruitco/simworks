"""Utilities for serializing ChatLab media payloads.

These helpers keep message/media payload shapes consistent across:
- REST API message responses
- Outbox event payloads
- WebSocket delivery (including catch-up replay)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.core.exceptions import SynchronousOnlyOperation


def _normalize_path(path: str | None) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        return f"/{path}"
    return path


def to_absolute_url(
    path: str | None,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> str:
    """Return an absolute URL when enough context exists, else normalized path."""
    normalized = _normalize_path(path)
    if not normalized:
        return ""

    if normalized.startswith(("http://", "https://")):
        return normalized

    if request is not None:
        return request.build_absolute_uri(normalized)

    if host:
        resolved_scheme = scheme or "http"
        return f"{resolved_scheme}://{host}{normalized}"

    return normalized


def serialize_media_item(
    media,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Serialize a SimulationImage to API/WebSocket-safe payload."""
    original_url = ""
    thumbnail_url = ""
    if getattr(media, "original", None):
        original_url = to_absolute_url(
            media.original.url, request=request, scheme=scheme, host=host
        )
    if getattr(media, "thumbnail", None):
        thumbnail_url = to_absolute_url(
            media.thumbnail.url,
            request=request,
            scheme=scheme,
            host=host,
        )

    return {
        "id": media.id,
        "uuid": str(media.uuid),
        "original_url": original_url,
        "thumbnail_url": thumbnail_url,
        "url": thumbnail_url,  # compatibility with existing web renderer
        "mime_type": media.mime_type or "",
        "description": media.description or "",
    }


def serialize_media_list(
    media_list: Iterable,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> list[dict[str, Any]]:
    return [
        serialize_media_item(media, request=request, scheme=scheme, host=host)
        for media in media_list
    ]


def build_message_media_payload(
    message,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Build canonical + compatibility media payload keys for a Message."""
    prefetched_media = getattr(message, "_prefetched_objects_cache", {}).get("media")
    if prefetched_media is not None:
        media_items = prefetched_media
    else:
        try:
            media_items = list(message.media.all())
        except SynchronousOnlyOperation:
            media_items = []

    items = serialize_media_list(
        media_items,
        request=request,
        scheme=scheme,
        host=host,
    )
    return {
        "media_list": items,
        "mediaList": items,
    }


def resolve_message_conversation_type(
    message,
    *,
    fallback: str | None = None,
) -> str | None:
    """Resolve conversation type slug without forcing lazy DB access in async contexts."""
    conversation = getattr(message, "conversation", None)
    if conversation is None:
        return fallback
    try:
        return getattr(conversation.conversation_type, "slug", fallback)
    except (AttributeError, SynchronousOnlyOperation):
        return fallback


def build_chat_message_event_payload(
    message,
    *,
    request=None,
    scheme: str | None = None,
    host: str | None = None,
    conversation_type: str | None = None,
    fallback_conversation_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build the canonical outbox/WebSocket payload for ``chat.message_created``."""
    resolved_conversation_type = conversation_type or resolve_message_conversation_type(
        message,
        fallback=fallback_conversation_type,
    )
    delivery_status = getattr(message, "delivery_status", "") or ""
    delivery_retryable = getattr(message, "delivery_retryable", None)
    delivery_error_code = getattr(message, "delivery_error_code", "") or ""
    delivery_error_text = getattr(message, "delivery_error_text", "") or ""
    payload = {
        "id": message.id,
        "message_id": message.id,
        "content": message.content or "",
        "role": message.role,
        "is_from_ai": message.is_from_ai,
        "isFromAi": message.is_from_ai,
        "isFromAI": message.is_from_ai,
        "display_name": message.display_name or "",
        "displayName": message.display_name or "",
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
        "conversation_id": message.conversation_id,
        "conversation_type": resolved_conversation_type,
        "messageType": message.message_type,
        "sender_id": message.sender_id,
        "senderId": message.sender_id,
        "status": status if status is not None else delivery_status or "completed",
        "delivery_status": delivery_status,
        "delivery_retryable": delivery_retryable,
        "delivery_error_code": delivery_error_code,
        "delivery_error_text": delivery_error_text,
        "source_message_id": message.source_message_id,
    }
    if hasattr(message, "image_requested"):
        payload["image_requested"] = bool(message.image_requested)
    payload.update(
        build_message_media_payload(
            message,
            request=request,
            scheme=scheme,
            host=host,
        )
    )
    return payload


def payload_message_id(payload: dict[str, Any]) -> int | None:
    """Extract message id from mixed legacy/modern payloads."""
    message_id = payload.get("message_id") or payload.get("id")
    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None
