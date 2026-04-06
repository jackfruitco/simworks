"""Message schemas for API v1."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MessageMediaOut(BaseModel):
    """Media attachment metadata for a message."""

    id: int = Field(..., description="SimulationImage ID")
    uuid: str = Field(..., description="SimulationImage UUID")
    original_url: str = Field(..., description="Absolute URL to original image")
    thumbnail_url: str = Field(..., description="Absolute URL to thumbnail image")
    mime_type: str = Field(default="", description="Media MIME type")
    description: str = Field(default="", description="Short media description")


class MessageOut(BaseModel):
    """Output schema for a chat message."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Message ID")
    simulation_id: int = Field(..., description="Simulation ID this message belongs to")
    conversation_id: int | None = Field(
        default=None, description="Conversation ID this message belongs to"
    )
    conversation_type: str | None = Field(
        default=None,
        description="Conversation type slug (e.g. 'simulated_patient', 'simulated_feedback')",
    )
    sender_id: int = Field(..., description="ID of the user who sent the message")
    content: str | None = Field(default=None, description="Message content")
    role: Literal["user", "assistant"] = Field(
        ...,
        description="Role of the message sender",
    )
    message_type: Literal["text", "image", "video", "audio", "file", "system"] = Field(
        default="text",
        description="Type of message",
    )
    timestamp: datetime = Field(..., description="When the message was created")
    is_from_ai: bool = Field(..., description="Whether this message is from the AI")
    display_name: str = Field(default="", description="Display name for the sender")
    delivery_status: Literal["sent", "delivered", "failed"] = Field(
        default="sent",
        description="Delivery status of outgoing messages",
    )
    delivery_error_code: str = Field(
        default="",
        description="Machine-readable delivery error code",
    )
    delivery_error_text: str = Field(
        default="",
        description="User-safe delivery error text",
    )
    delivery_retryable: bool = Field(
        default=True,
        description="Whether the message can be retried by the user",
    )
    delivery_retry_count: int = Field(
        default=0,
        description="How many user retries have been attempted for this message",
    )
    is_read: bool = Field(
        default=False,
        description="Whether the current user has read this message",
    )
    media_list: list[MessageMediaOut] = Field(
        default_factory=list,
        description="Message media metadata (snake_case canonical API shape)",
    )


class MessageCreate(BaseModel):
    """Input schema for creating a message."""

    content: str = Field(
        ...,
        description="Message content",
        min_length=1,
        max_length=10000,
    )
    message_type: Literal["text"] = Field(
        default="text",
        description="Type of message (only 'text' supported via API)",
    )
    conversation_id: int | None = Field(
        default=None,
        description="Target conversation ID. Defaults to patient conversation if omitted.",
    )


class MessageListResponse(BaseModel):
    """Response for listing messages with cursor pagination."""

    items: list[MessageOut] = Field(
        ...,
        description="List of messages",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Cursor for fetching the next page (message ID)",
    )
    has_more: bool = Field(
        ...,
        description="Whether more messages exist",
    )


# Role mapping for display
ROLE_MAP = {
    "U": "user",
    "A": "assistant",
}


def message_to_out(msg, request=None) -> MessageOut:
    """Convert a Message model instance to MessageOut schema.

    Handles both messages with and without conversation (backward compat).
    Uses select_related("conversation__conversation_type") when available.
    """
    conversation_type = None
    conv_id = getattr(msg, "conversation_id", None)
    if conv_id:
        try:
            # Works when select_related("conversation__conversation_type") was used
            conversation_type = msg.conversation.conversation_type.slug
        except AttributeError:
            pass

    from apps.chatlab.media_payloads import build_message_media_payload

    media_payload = build_message_media_payload(msg, request=request)

    return MessageOut(
        id=msg.pk,
        simulation_id=msg.simulation_id,
        conversation_id=conv_id,
        conversation_type=conversation_type,
        sender_id=msg.sender_id,
        content=msg.content,
        role=ROLE_MAP.get(msg.role, "user"),
        message_type=msg.message_type,
        timestamp=msg.timestamp,
        is_from_ai=msg.is_from_ai,
        display_name=msg.display_name or "",
        delivery_status=getattr(msg, "delivery_status", "sent"),
        delivery_error_code=getattr(msg, "delivery_error_code", ""),
        delivery_error_text=getattr(msg, "delivery_error_text", ""),
        delivery_retryable=getattr(msg, "delivery_retryable", True),
        delivery_retry_count=getattr(msg, "delivery_retry_count", 0),
        is_read=bool(getattr(msg, "is_read", False)),
        media_list=media_payload.get("media_list", []),
    )
