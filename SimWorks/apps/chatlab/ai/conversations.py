"""Durable synchronization between MedSim messages and OpenAI Conversations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
import httpx

from apps.chatlab.models import Message, ProviderConversationItem, RoleChoices
from config.logging import get_logger
from orchestrai.utils.env_utils import get_api_key

logger = get_logger(__name__)


class ProviderConversationError(RuntimeError):
    """The provider conversation could not be created or updated."""


class ProviderConversationNotFound(ProviderConversationError):
    """The provider conversation was deleted or is otherwise unrecoverable."""


@dataclass(frozen=True)
class ProviderConversation:
    id: str


def conversations_url() -> str:
    base_url = getattr(settings, "OPENAI_API_BASE_URL", "https://api.openai.com/v1")
    return f"{str(base_url).rstrip('/')}/conversations"


def _api_key() -> str | None:
    return getattr(settings, "OPENAI_API_KEY", None) or get_api_key("openai")


def _headers(*, idempotency_key: str | None = None) -> dict[str, str]:
    api_key = _api_key()
    if not api_key:
        raise ProviderConversationError("OpenAI Responses provider is not configured")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _json_response(response: httpx.Response, *, operation: str) -> dict[str, Any]:
    if response.status_code == 404:
        raise ProviderConversationNotFound(f"OpenAI conversation not found during {operation}")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderConversationError(
            f"OpenAI conversation {operation} failed with HTTP {response.status_code}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderConversationError(
            f"OpenAI conversation {operation} returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderConversationError(
            f"OpenAI conversation {operation} returned an invalid payload"
        )
    return payload


def _provider_id(payload: dict[str, Any], *, operation: str) -> str:
    provider_id = payload.get("id")
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ProviderConversationError(
            f"OpenAI conversation {operation} response did not include an ID"
        )
    return provider_id.strip()


def _provider_item_id(payload: dict[str, Any], *, fallback: str) -> str:
    provider_id = payload.get("id")
    if isinstance(provider_id, str) and provider_id.strip():
        return provider_id.strip()
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        provider_id = data[0].get("id")
        if isinstance(provider_id, str) and provider_id.strip():
            return provider_id.strip()
    return fallback


def create_provider_conversation() -> ProviderConversation:
    """Create an empty durable OpenAI Responses conversation."""

    try:
        response = httpx.post(
            conversations_url(),
            headers=_headers(),
            json={},
            timeout=getattr(settings, "OPENAI_CONVERSATION_TIMEOUT_SECONDS", 10.0),
        )
    except httpx.HTTPError as exc:
        raise ProviderConversationError("OpenAI conversation provider is unavailable") from exc
    return ProviderConversation(
        _provider_id(_json_response(response, operation="create"), operation="create")
    )


def ensure_provider_conversation(conversation) -> ProviderConversation:
    """Resolve or create one provider conversation for a MedSim conversation.

    The row lock makes the check/create/save sequence safe for concurrent first
    turns. The provider ID is only committed after the provider create succeeds.
    """

    if conversation.provider_conversation_id:
        return ProviderConversation(conversation.provider_conversation_id)

    with transaction.atomic():
        locked = type(conversation).objects.select_for_update().get(pk=conversation.pk)
        if locked.provider_conversation_id:
            conversation.provider_conversation_id = locked.provider_conversation_id
            conversation.provider_sync_status = locked.provider_sync_status
            conversation.provider_sync_cursor = locked.provider_sync_cursor
            conversation.provider_sync_error = locked.provider_sync_error
            return ProviderConversation(locked.provider_conversation_id)

        provider_conversation = create_provider_conversation()
        locked.provider_conversation_id = provider_conversation.id
        locked.provider_sync_status = "pending"
        locked.provider_sync_error = ""
        locked.save(
            update_fields=[
                "provider_conversation_id",
                "provider_sync_status",
                "provider_sync_error",
            ]
        )
        conversation.provider_conversation_id = locked.provider_conversation_id
        conversation.provider_sync_status = locked.provider_sync_status
        conversation.provider_sync_cursor = locked.provider_sync_cursor
        conversation.provider_sync_error = locked.provider_sync_error
        return provider_conversation


def rebuild_provider_conversation(conversation) -> ProviderConversation:
    """Replace a deleted provider conversation so canonical history can recover it."""

    with transaction.atomic():
        locked = type(conversation).objects.select_for_update().get(pk=conversation.pk)
        provider_conversation = create_provider_conversation()
        locked.provider_conversation_id = provider_conversation.id
        locked.provider_sync_cursor = None
        locked.provider_sync_status = "pending"
        locked.provider_sync_error = ""
        locked.save(
            update_fields=[
                "provider_conversation_id",
                "provider_sync_cursor",
                "provider_sync_status",
                "provider_sync_error",
            ]
        )
        conversation.provider_conversation_id = locked.provider_conversation_id
        conversation.provider_sync_cursor = locked.provider_sync_cursor
        conversation.provider_sync_status = locked.provider_sync_status
        conversation.provider_sync_error = locked.provider_sync_error
        return provider_conversation


def medsim_message_to_response_item(message: Message) -> dict[str, Any]:
    """Map one canonical text message to a Responses Conversation item."""

    role = "assistant" if message.role == RoleChoices.ASSISTANT else "user"
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text", "text": str(message.content or "")}],
    }


def _append_provider_item(*, provider_conversation_id: str, message: Message) -> str:
    item = medsim_message_to_response_item(message)
    idempotency_key = hashlib.sha256(
        f"medsim:responses:{provider_conversation_id}:message:{message.pk}".encode()
    ).hexdigest()
    try:
        response = httpx.post(
            f"{conversations_url()}/{provider_conversation_id}/items",
            headers=_headers(idempotency_key=idempotency_key),
            json={"items": [item]},
            timeout=getattr(settings, "OPENAI_CONVERSATION_TIMEOUT_SECONDS", 10.0),
        )
    except httpx.HTTPError as exc:
        raise ProviderConversationError("OpenAI conversation provider is unavailable") from exc
    payload = _json_response(response, operation="append item")
    return _provider_item_id(payload, fallback=f"medsim-message-{message.pk}")


def _record_synced_item(
    *, conversation, message: Message, provider_conversation_id: str, provider_item_id: str
) -> None:
    try:
        ProviderConversationItem.objects.create(
            conversation=conversation,
            message=message,
            provider_conversation_id=provider_conversation_id,
            provider_item_id=provider_item_id,
            item_type="message",
        )
    except IntegrityError:
        if not ProviderConversationItem.objects.filter(
            conversation=conversation,
            message=message,
            provider_conversation_id=provider_conversation_id,
        ).exists():
            raise


def sync_messages_to_provider(
    conversation,
    *,
    after_message_id: int | None = None,
    through_message_id: int | None = None,
) -> int | None:
    """Append canonical messages not yet present in the provider conversation.

    Each append has a deterministic provider idempotency key and a local receipt.
    The cursor advances only after the receipt is durable, so a failed append
    remains pending and is retried by the next text or voice boundary.
    """

    provider_conversation = ensure_provider_conversation(conversation)
    lower_bound = (
        after_message_id if after_message_id is not None else conversation.provider_sync_cursor
    )
    messages = (
        Message.objects.filter(
            conversation_id=conversation.pk,
            simulation_id=conversation.simulation_id,
            is_deleted=False,
            message_type=Message.MessageType.TEXT,
            pk__gt=lower_bound or 0,
        )
        .exclude(content__isnull=True)
        .exclude(content="")
        .order_by("pk")
    )
    if through_message_id is not None:
        messages = messages.filter(pk__lte=through_message_id)

    last_message_id = lower_bound
    try:
        for message in messages:
            receipt = ProviderConversationItem.objects.filter(
                conversation=conversation,
                message=message,
                provider_conversation_id=provider_conversation.id,
            ).first()
            if receipt is None:
                provider_item_id = _append_provider_item(
                    provider_conversation_id=provider_conversation.id,
                    message=message,
                )
                _record_synced_item(
                    conversation=conversation,
                    message=message,
                    provider_conversation_id=provider_conversation.id,
                    provider_item_id=provider_item_id,
                )
            last_message_id = message.pk
            conversation.provider_sync_cursor = message.pk
            conversation.provider_sync_status = "synced"
            conversation.provider_sync_error = ""
            conversation.save(
                update_fields=[
                    "provider_sync_cursor",
                    "provider_sync_status",
                    "provider_sync_error",
                ]
            )
    except ProviderConversationNotFound:
        logger.warning(
            "chatlab.provider_conversation_missing conversation=%s; rebuilding",
            conversation.pk,
        )
        rebuild_provider_conversation(conversation)
        return sync_messages_to_provider(
            conversation,
            after_message_id=None,
            through_message_id=through_message_id,
        )
    except ProviderConversationError as exc:
        conversation.provider_sync_status = "failed"
        conversation.provider_sync_error = str(exc)[:2000]
        conversation.save(update_fields=["provider_sync_status", "provider_sync_error"])
        raise

    if last_message_id is None:
        conversation.provider_sync_status = "synced"
        conversation.provider_sync_error = ""
        conversation.save(update_fields=["provider_sync_status", "provider_sync_error"])
    return last_message_id


def sync_voice_session_to_provider(voice_session) -> int | None:
    """Append a voice session's canonical transcripts to its Responses conversation."""

    try:
        provider_cursor = sync_messages_to_provider(
            voice_session.conversation,
            after_message_id=voice_session.responses_sync_cursor or 0,
        )
    except ProviderConversationError as exc:
        voice_session.responses_sync_status = "pending"
        voice_session.responses_sync_error = str(exc)[:2000]
        voice_session.save(
            update_fields=["responses_sync_status", "responses_sync_error", "updated_at"]
        )
        raise

    voice_session.responses_sync_cursor = provider_cursor
    voice_session.responses_sync_status = "synced"
    voice_session.responses_sync_error = ""
    voice_session.save(
        update_fields=[
            "responses_sync_cursor",
            "responses_sync_status",
            "responses_sync_error",
            "updated_at",
        ]
    )
    return provider_cursor


def mark_message_synced_to_provider(
    *, conversation, message: Message, provider_item_id: str, item_type: str = "message"
) -> None:
    """Record a message already appended by a Responses request."""

    provider_conversation_id = conversation.provider_conversation_id
    if not provider_conversation_id:
        return
    _record_synced_item(
        conversation=conversation,
        message=message,
        provider_conversation_id=provider_conversation_id,
        provider_item_id=provider_item_id,
        item_type=item_type,
    )
    if conversation.provider_sync_cursor is None or message.pk > conversation.provider_sync_cursor:
        conversation.provider_sync_cursor = message.pk
    conversation.provider_sync_status = "synced"
    conversation.provider_sync_error = ""
    conversation.save(
        update_fields=[
            "provider_sync_cursor",
            "provider_sync_status",
            "provider_sync_error",
        ]
    )


__all__ = [
    "ProviderConversation",
    "ProviderConversationError",
    "ProviderConversationNotFound",
    "create_provider_conversation",
    "ensure_provider_conversation",
    "mark_message_synced_to_provider",
    "medsim_message_to_response_item",
    "rebuild_provider_conversation",
    "sync_messages_to_provider",
    "sync_voice_session_to_provider",
]
