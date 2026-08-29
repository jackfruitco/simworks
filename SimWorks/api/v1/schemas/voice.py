"""VoiceLab API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from api.v1.schemas.messages import MessageOut, message_to_out

VoiceSessionStatus = Literal["configuring", "active", "ended", "failed"]
VoiceTransport = Literal["webrtc", "websocket"]
VoiceTranscriptRole = Literal["user", "assistant"]
VoiceTranscriptStatus = Literal["final", "completed"]


class VoiceSessionCreate(BaseModel):
    """Input schema for starting a VoiceLab session."""

    conversation_id: int | None = Field(
        default=None,
        description="Target conversation ID. Defaults to the simulated patient conversation.",
    )
    transport: VoiceTransport = Field(
        default="webrtc",
        description="Realtime audio transport requested by the client.",
    )
    model: str | None = Field(
        default=None,
        max_length=100,
        description="Optional provider realtime model override.",
    )
    voice: str | None = Field(
        default=None,
        max_length=100,
        description="Optional provider voice override.",
    )
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description=("Client-generated key used to make voice session start safe to retry."),
    )
    client_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive client details for diagnostics and lifecycle tracking.",
    )


class VoiceSessionOut(BaseModel):
    """VoiceLab session broker response."""

    id: int = Field(..., description="VoiceSession database ID")
    uuid: str = Field(..., description="Stable VoiceSession UUID")
    simulation_id: int = Field(..., description="Simulation ID")
    conversation_id: int = Field(..., description="Conversation ID")
    status: VoiceSessionStatus = Field(..., description="Voice session lifecycle status")
    transport: VoiceTransport = Field(..., description="Realtime transport")
    provider: str = Field(..., description="Realtime provider")
    provider_session_id: str = Field(default="", description="Provider session identifier")
    model: str = Field(..., description="Realtime model")
    voice: str = Field(..., description="Realtime voice")
    created_at: datetime = Field(..., description="When the VoiceSession was created")
    updated_at: datetime = Field(..., description="When the VoiceSession was last updated")
    ended_at: datetime | None = Field(default=None, description="When the VoiceSession ended")
    expires_at: datetime | None = Field(default=None, description="When the client secret expires")
    realtime_url: str | None = Field(
        default=None,
        description="Provider endpoint used to mint the client secret.",
    )
    calls_url: str | None = Field(
        default=None,
        description="Provider WebRTC SDP endpoint for the client.",
    )
    websocket_url: str | None = Field(
        default=None,
        description="Provider WebSocket endpoint for the client.",
    )
    client_secret: dict[str, Any] | None = Field(
        default=None,
        description="Ephemeral provider client secret. Returned only when starting a session.",
    )
    session_config: dict[str, Any] | None = Field(
        default=None,
        description="Provider session config used to mint the client secret.",
    )


class VoiceTranscriptCreate(BaseModel):
    """Final Realtime transcript to persist into ChatLab history."""

    role: VoiceTranscriptRole = Field(..., description="Speaker role for the transcript")
    transcript: str = Field(
        ...,
        min_length=1,
        max_length=20000,
        description="Final transcript text from the Realtime session.",
    )
    status: VoiceTranscriptStatus = Field(
        default="final",
        description="Final transcript status; partial transcripts are not persisted.",
    )
    provider_item_id: str | None = Field(
        default=None,
        max_length=255,
        description="Provider conversation item ID used for idempotency.",
    )
    provider_response_id: str | None = Field(
        default=None,
        max_length=255,
        description="Provider response ID used for idempotency.",
    )
    provider_event_id: str | None = Field(
        default=None,
        max_length=255,
        description="Provider event ID used as a fallback idempotency key.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive provider/client transcript metadata.",
    )


class VoiceTranscriptOut(BaseModel):
    """Result of persisting a final VoiceLab transcript."""

    persisted: bool = Field(..., description="True when a new message was created")
    message: MessageOut = Field(..., description="Persisted ChatLab message")


class VoiceToolCallCreate(BaseModel):
    """Realtime tool call forwarded by the iOS client for backend execution."""

    tool_call_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Provider tool/function call ID.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Tool/function name requested by the Realtime model.",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Parsed JSON arguments for the tool call.",
    )


class VoiceToolCallOut(BaseModel):
    """Backend tool execution result for the iOS client to return to Realtime."""

    tool_call_id: str = Field(..., description="Provider tool/function call ID")
    name: str = Field(..., description="Tool/function name")
    status: Literal["completed"] = Field(default="completed", description="Execution status")
    output: dict[str, Any] = Field(..., description="JSON-serializable tool output")


def voice_session_to_out(voice_session, start=None) -> VoiceSessionOut:
    """Convert a VoiceSession model into API output."""

    return VoiceSessionOut(
        id=voice_session.pk,
        uuid=str(voice_session.uuid),
        simulation_id=voice_session.simulation_id,
        conversation_id=voice_session.conversation_id,
        status=voice_session.status,
        transport=voice_session.transport,
        provider=voice_session.provider,
        provider_session_id=voice_session.provider_session_id,
        model=voice_session.model_name,
        voice=voice_session.voice_name,
        created_at=voice_session.created_at,
        updated_at=voice_session.updated_at,
        ended_at=voice_session.ended_at,
        expires_at=voice_session.expires_at,
        realtime_url=getattr(start, "realtime_url", None),
        calls_url=getattr(start, "calls_url", None),
        websocket_url=getattr(start, "websocket_url", None),
        client_secret=getattr(start, "client_secret", None),
        session_config=getattr(start, "session_config", None),
    )


def voice_transcript_to_out(message, *, persisted: bool, request=None) -> VoiceTranscriptOut:
    """Convert a persisted voice transcript message into API output."""

    return VoiceTranscriptOut(
        persisted=persisted,
        message=message_to_out(message, request=request),
    )
