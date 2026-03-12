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


def payload_message_id(payload: dict[str, Any]) -> int | None:
    """Extract message id from mixed legacy/modern payloads."""
    message_id = payload.get("message_id") or payload.get("id")
    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None
