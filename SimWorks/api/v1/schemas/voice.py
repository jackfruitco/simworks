"""VoiceLab API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

VoiceSessionStatus = Literal["configuring", "active", "ended", "failed"]
VoiceTransport = Literal["webrtc", "websocket"]


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
    client_secret: dict[str, Any] | None = Field(
        default=None,
        description="Ephemeral provider client secret. Returned only when starting a session.",
    )
    session_config: dict[str, Any] | None = Field(
        default=None,
        description="Provider session config used to mint the client secret.",
    )


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
        client_secret=getattr(start, "client_secret", None),
        session_config=getattr(start, "session_config", None),
    )
