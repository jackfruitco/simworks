"""Conversation schemas for API v1."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationOut(BaseModel):
    """Output schema for a conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Conversation ID")
    uuid: str = Field(..., description="Conversation UUID")
    simulation_id: int = Field(..., description="Simulation this conversation belongs to")
    conversation_type: str = Field(..., description="Conversation type slug")
    conversation_type_display: str = Field(..., description="Human-readable type name")
    icon: str = Field(default="", description="Iconify icon for this conversation type")
    display_name: str = Field(default="", description="Display name for the conversation partner")
    display_initials: str = Field(default="", description="Initials for avatar display")
    is_locked: bool = Field(..., description="Whether this conversation is read-only")
    created_at: datetime = Field(..., description="When the conversation was created")


class ConversationCreate(BaseModel):
    """Input schema for creating a conversation."""

    conversation_type: str = Field(
        ...,
        description="Conversation type slug (e.g. 'simulated_feedback')",
        min_length=1,
        max_length=40,
    )


class ConversationListResponse(BaseModel):
    """Response for listing conversations."""

    items: list[ConversationOut] = Field(
        ...,
        description="List of conversations",
    )


def conversation_to_out(conv) -> ConversationOut:
    """Convert a Conversation model instance to ConversationOut schema.

    Requires ``conv.conversation_type`` to be pre-fetched (select_related).
    """
    return ConversationOut(
        id=conv.pk,
        uuid=str(conv.uuid),
        simulation_id=conv.simulation_id,
        conversation_type=conv.conversation_type.slug,
        conversation_type_display=conv.conversation_type.display_name,
        icon=conv.conversation_type.icon or "",
        display_name=conv.display_name or "",
        display_initials=conv.display_initials or "",
        is_locked=conv.is_locked,
        created_at=conv.created_at,
    )
