"""Message schemas for API v1."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    """Output schema for a chat message."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Message ID")
    simulation_id: int = Field(..., description="Simulation ID this message belongs to")
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
    order: int | None = Field(default=None, description="Message order in the simulation")
    display_name: str = Field(default="", description="Display name for the sender")


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


def message_to_out(msg) -> MessageOut:
    """Convert a Message model instance to MessageOut schema."""
    return MessageOut(
        id=msg.pk,
        simulation_id=msg.simulation_id,
        sender_id=msg.sender_id,
        content=msg.content,
        role=ROLE_MAP.get(msg.role, "user"),
        message_type=msg.message_type,
        timestamp=msg.timestamp,
        is_from_ai=msg.is_from_ai,
        order=msg.order,
        display_name=msg.display_name or "",
    )
