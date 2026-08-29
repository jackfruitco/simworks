"""VoiceLab session broker services for ChatLab-backed simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
import httpx
from ninja.errors import HttpError

from apps.chatlab.models import VoiceSession
from apps.common.outbox import enqueue_event_sync, event_types as outbox_events, poke_drain_sync
from apps.simcore.models import Simulation
from config.logging import get_logger

logger = get_logger(__name__)


class VoiceProviderConfigurationError(RuntimeError):
    """Raised when the voice provider is not configured for live sessions."""


class VoiceProviderError(RuntimeError):
    """Raised when the upstream realtime provider rejects a session request."""


@dataclass(frozen=True)
class VoiceSessionStart:
    """Provider artifacts returned to the mobile client for a live session."""

    client_secret: dict[str, Any]
    session_config: dict[str, Any]
    realtime_url: str
    calls_url: str
    expires_at: datetime | None = None
    provider_session_id: str = ""
    provider_metadata: dict[str, Any] | None = None


def default_realtime_model() -> str:
    return getattr(settings, "VOICELAB_REALTIME_MODEL", "gpt-realtime-2.1")


def default_voice_name() -> str:
    return getattr(settings, "VOICELAB_REALTIME_VOICE", "marin")


def realtime_client_secrets_url() -> str:
    return getattr(
        settings,
        "VOICELAB_OPENAI_CLIENT_SECRETS_URL",
        "https://api.openai.com/v1/realtime/client_secrets",
    )


def realtime_calls_url() -> str:
    return getattr(
        settings,
        "VOICELAB_OPENAI_CALLS_URL",
        "https://api.openai.com/v1/realtime/calls",
    )


def _stable_safety_identifier(user) -> str:
    raw = f"{settings.SECRET_KEY}:voice:{getattr(user, 'pk', '')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_unix_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _redact_secret_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    if isinstance(redacted.get("value"), str):
        redacted["value"] = "[redacted]"
    if isinstance(redacted.get("client_secret"), dict):
        redacted["client_secret"] = _redact_secret_payload(redacted["client_secret"])
    return redacted


def build_realtime_session_config(
    *,
    simulation: Simulation,
    conversation,
    model: str,
    voice: str,
) -> dict[str, Any]:
    """Build the provider session config sent when minting an ephemeral secret."""

    patient_name = (
        simulation.sim_patient_display_name or simulation.sim_patient_full_name or "the patient"
    )
    chief_complaint = simulation.chief_complaint or "the presenting concern"
    conversation_name = conversation.display_name or conversation.conversation_type.display_name
    instructions = (
        "You are running a MedSim ChatLab voice encounter. "
        f"Speak as {conversation_name}, the simulated patient, unless the configured "
        "conversation persona says otherwise. Keep responses conversational, clinically "
        "consistent, and concise enough for spoken turn-taking. "
        f"The patient is {patient_name}; the chief complaint is {chief_complaint}."
    )
    return {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "audio": {
            "input": {
                "turn_detection": {
                    "type": "server_vad",
                },
            },
            "output": {
                "voice": voice,
            },
        },
        "metadata": {
            "simulation_id": str(simulation.pk),
            "conversation_id": str(conversation.pk),
            "lab": "voicelab",
        },
    }


class OpenAIRealtimeSessionBroker:
    """Mint ephemeral OpenAI Realtime client secrets for iOS WebRTC sessions."""

    def __init__(self, *, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def start_session(
        self,
        *,
        user,
        simulation: Simulation,
        conversation,
        transport: str,
        model: str,
        voice: str,
    ) -> VoiceSessionStart:
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise VoiceProviderConfigurationError(
                "OpenAI Realtime voice provider is not configured"
            )
        if transport != VoiceSession.Transport.WEBRTC:
            raise VoiceProviderConfigurationError(
                "Only WebRTC voice sessions are currently supported"
            )

        session_config = build_realtime_session_config(
            simulation=simulation,
            conversation=conversation,
            model=model,
            voice=voice,
        )
        try:
            response = httpx.post(
                realtime_client_secrets_url(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "OpenAI-Safety-Identifier": _stable_safety_identifier(user),
                },
                json={"session": session_config},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "voicelab.provider_rejected",
                status_code=exc.response.status_code,
                simulation_id=simulation.pk,
            )
            raise VoiceProviderError("Realtime provider rejected the session request") from exc
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "voicelab.provider_unavailable",
                simulation_id=simulation.pk,
                error=str(exc),
            )
            raise VoiceProviderError("Realtime provider is unavailable") from exc

        if not isinstance(payload, dict):
            raise VoiceProviderError("Realtime provider returned an invalid session payload")

        client_secret = (
            payload.get("client_secret")
            if isinstance(payload.get("client_secret"), dict)
            else payload
        )
        if not isinstance(client_secret, dict):
            raise VoiceProviderError("Realtime provider returned an invalid client secret")
        expires_at = _parse_unix_timestamp(
            client_secret.get("expires_at") if isinstance(client_secret, dict) else None
        ) or _parse_unix_timestamp(payload.get("expires_at"))
        provider_session_id = str(payload.get("id") or payload.get("session_id") or "")
        return VoiceSessionStart(
            client_secret=client_secret,
            session_config=session_config,
            realtime_url=realtime_client_secrets_url(),
            calls_url=realtime_calls_url(),
            expires_at=expires_at,
            provider_session_id=provider_session_id,
            provider_metadata=_redact_secret_payload(payload),
        )


def _emit_voice_session_event(
    voice_session: VoiceSession, *, event_type: str, correlation_id: str | None
) -> None:
    event = enqueue_event_sync(
        event_type=event_type,
        simulation_id=voice_session.simulation_id,
        payload={
            "voice_session_id": voice_session.pk,
            "voice_session_uuid": str(voice_session.uuid),
            "simulation_id": voice_session.simulation_id,
            "conversation_id": voice_session.conversation_id,
            "status": voice_session.status,
            "transport": voice_session.transport,
            "provider": voice_session.provider,
            "model": voice_session.model_name,
            "voice": voice_session.voice_name,
            "expires_at": voice_session.expires_at.isoformat()
            if voice_session.expires_at
            else None,
        },
        idempotency_key=f"{event_type}:{voice_session.pk}:{voice_session.status}",
        correlation_id=correlation_id,
    )
    if event:
        poke_drain_sync()


def create_voice_session(
    *,
    user,
    simulation: Simulation,
    conversation,
    transport: str,
    model: str | None,
    voice: str | None,
    client_metadata: dict[str, Any] | None = None,
    broker: OpenAIRealtimeSessionBroker | None = None,
    correlation_id: str | None = None,
) -> tuple[VoiceSession, VoiceSessionStart]:
    """Create a VoiceSession and return provider connection material."""

    selected_model = model or default_realtime_model()
    selected_voice = voice or default_voice_name()
    broker = broker or OpenAIRealtimeSessionBroker()

    with transaction.atomic():
        voice_session = VoiceSession.objects.create(
            simulation=simulation,
            conversation=conversation,
            created_by=user,
            status=VoiceSession.Status.CONFIGURING,
            transport=transport,
            model_name=selected_model,
            voice_name=selected_voice,
            client_metadata=client_metadata or {},
        )

    try:
        start = broker.start_session(
            user=user,
            simulation=simulation,
            conversation=conversation,
            transport=transport,
            model=selected_model,
            voice=selected_voice,
        )
    except VoiceProviderConfigurationError as exc:
        voice_session.status = VoiceSession.Status.FAILED
        voice_session.last_error_code = "provider_not_configured"
        voice_session.last_error_text = str(exc)
        voice_session.save(
            update_fields=["status", "last_error_code", "last_error_text", "updated_at"]
        )
        _emit_voice_session_event(
            voice_session,
            event_type=outbox_events.VOICE_SESSION_UPDATED,
            correlation_id=correlation_id,
        )
        raise HttpError(503, str(exc)) from exc
    except VoiceProviderError as exc:
        voice_session.status = VoiceSession.Status.FAILED
        voice_session.last_error_code = "provider_unavailable"
        voice_session.last_error_text = str(exc)
        voice_session.save(
            update_fields=["status", "last_error_code", "last_error_text", "updated_at"]
        )
        _emit_voice_session_event(
            voice_session,
            event_type=outbox_events.VOICE_SESSION_UPDATED,
            correlation_id=correlation_id,
        )
        raise HttpError(502, str(exc)) from exc

    voice_session.status = VoiceSession.Status.ACTIVE
    voice_session.expires_at = start.expires_at
    voice_session.provider_session_id = start.provider_session_id
    voice_session.provider_metadata = start.provider_metadata or {}
    voice_session.save(
        update_fields=[
            "status",
            "expires_at",
            "provider_session_id",
            "provider_metadata",
            "updated_at",
        ]
    )
    _emit_voice_session_event(
        voice_session,
        event_type=outbox_events.VOICE_SESSION_CREATED,
        correlation_id=correlation_id,
    )
    return voice_session, start


def end_voice_session(
    *,
    voice_session: VoiceSession,
    correlation_id: str | None = None,
) -> VoiceSession:
    """Mark a live voice session ended and emit a durable lifecycle event."""

    if voice_session.status == VoiceSession.Status.ENDED:
        return voice_session
    voice_session.status = VoiceSession.Status.ENDED
    voice_session.ended_at = timezone.now()
    voice_session.save(update_fields=["status", "ended_at", "updated_at"])
    _emit_voice_session_event(
        voice_session,
        event_type=outbox_events.VOICE_SESSION_UPDATED,
        correlation_id=correlation_id,
    )
    return voice_session
