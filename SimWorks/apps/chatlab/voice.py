"""VoiceLab session broker services for ChatLab-backed simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
import httpx
from ninja.errors import HttpError

from apps.chatlab.media_payloads import build_chat_message_event_payload
from apps.chatlab.models import Message, RoleChoices, VoiceSession
from apps.common.outbox import enqueue_event_sync, event_types as outbox_events, poke_drain_sync
from apps.common.utils.accounts import get_or_create_system_user
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


def default_transcription_model() -> str:
    return getattr(settings, "VOICELAB_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")


def context_message_limit() -> int:
    return max(0, int(getattr(settings, "VOICELAB_CONTEXT_MESSAGE_LIMIT", 12)))


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


def _voice_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "patient_history",
            "description": "Fetch known patient history and demographics for this simulation.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "patient_results",
            "description": "Fetch available lab and imaging results for this simulation.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "simulation_metadata",
            "description": "Fetch structured simulation metadata useful for clinical context.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "sign_lab_orders",
            "description": (
                "Submit lab orders requested by the learner. Use only when the learner "
                "clearly asks to order tests."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "orders": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 255},
                        "minItems": 1,
                        "maxItems": 50,
                    }
                },
                "required": ["orders"],
                "additionalProperties": False,
            },
        },
    ]


def _recent_conversation_context(conversation) -> str:
    limit = context_message_limit()
    if limit <= 0:
        return ""

    messages = list(
        Message.objects.filter(
            simulation_id=conversation.simulation_id,
            conversation_id=conversation.pk,
            is_deleted=False,
            message_type=Message.MessageType.TEXT,
        )
        .exclude(content__isnull=True)
        .exclude(content="")
        .order_by("-pk")[:limit]
    )
    if not messages:
        return ""

    lines = []
    for message in reversed(messages):
        label = "Learner" if message.role == RoleChoices.USER else "Patient"
        content = " ".join(str(message.content or "").split())
        if content:
            lines.append(f"{label}: {content}")
    if not lines:
        return ""
    return "Recent text conversation for continuity:\n" + "\n".join(lines)


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
    persona = getattr(conversation.conversation_type, "ai_persona", "") or "patient"
    recent_context = _recent_conversation_context(conversation)
    instructions = (
        "You are running a MedSim ChatLab voice encounter. "
        f"Speak as {conversation_name}, the simulated patient, unless the configured "
        f"conversation persona says otherwise. The configured persona is {persona}. "
        "Keep responses conversational, clinically "
        "consistent, and concise enough for spoken turn-taking. "
        f"The patient is {patient_name}; the chief complaint is {chief_complaint}. "
        "Use available tools when patient history, results, simulation metadata, or lab "
        "order submission is needed; do not invent unseen results."
    )
    if recent_context:
        instructions = f"{instructions}\n\n{recent_context}"
    return {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "audio": {
            "input": {
                "turn_detection": {
                    "type": "server_vad",
                },
                "transcription": {
                    "model": default_transcription_model(),
                },
            },
            "output": {
                "voice": voice,
            },
        },
        "tools": _voice_tool_definitions(),
        "tool_choice": "auto",
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


def _require_active_voice_session(voice_session: VoiceSession) -> None:
    if voice_session.status != VoiceSession.Status.ACTIVE:
        raise HttpError(400, "Voice session is not active")
    if voice_session.simulation.status != Simulation.SimulationStatus.IN_PROGRESS:
        raise HttpError(400, "Voice session simulation is no longer in progress")
    if voice_session.conversation.is_locked:
        raise HttpError(400, "This conversation is locked")


def _provider_message_id(
    *,
    provider_item_id: str | None,
    provider_response_id: str | None,
    provider_event_id: str | None,
) -> str:
    provider_id = provider_response_id or provider_item_id or provider_event_id or ""
    return provider_id[:255]


def _emit_message_created(message: Message, *, correlation_id: str | None) -> None:
    event = enqueue_event_sync(
        event_type=outbox_events.MESSAGE_CREATED,
        simulation_id=message.simulation_id,
        payload=build_chat_message_event_payload(
            message,
            conversation_type=message.conversation.conversation_type.slug,
            status="completed",
        ),
        idempotency_key=f"{outbox_events.MESSAGE_CREATED}:{message.id}",
        correlation_id=correlation_id,
    )
    if event:
        poke_drain_sync()


def persist_voice_transcript(
    *,
    voice_session: VoiceSession,
    user,
    role: str,
    transcript: str,
    provider_item_id: str | None = None,
    provider_response_id: str | None = None,
    provider_event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> tuple[Message, bool]:
    """Persist a final VoiceLab transcript as a normal ChatLab message."""

    _require_active_voice_session(voice_session)
    content = " ".join(transcript.split())
    if not content:
        raise HttpError(400, "transcript must contain non-empty text")

    provider_id = _provider_message_id(
        provider_item_id=provider_item_id,
        provider_response_id=provider_response_id,
        provider_event_id=provider_event_id,
    )
    if provider_id:
        existing = (
            Message.objects.filter(
                simulation=voice_session.simulation,
                conversation=voice_session.conversation,
                provider_response_id=provider_id,
            )
            .select_related("conversation__conversation_type")
            .first()
        )
        if existing:
            return existing, False

    is_assistant = role == "assistant"
    sender = get_or_create_system_user() if is_assistant else user
    if is_assistant:
        display_name = (
            voice_session.conversation.display_name
            or voice_session.simulation.sim_patient_display_name
            or "AI"
        )
    else:
        display_name = user.get_full_name() or user.email

    message = Message(
        simulation=voice_session.simulation,
        conversation=voice_session.conversation,
        sender=sender,
        content=content,
        role=RoleChoices.ASSISTANT if is_assistant else RoleChoices.USER,
        message_type=Message.MessageType.TEXT,
        is_from_ai=is_assistant,
        delivery_status=Message.DeliveryStatus.DELIVERED,
        delivery_retryable=False,
        provider_response_id=provider_id or None,
        display_name=display_name,
    )
    message._outbox_correlation_id = correlation_id
    message.save()

    if is_assistant:
        _emit_message_created(message, correlation_id=correlation_id)
    return message, True


def execute_voice_tool_call(
    *,
    voice_session: VoiceSession,
    name: str,
    arguments: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Execute a server-authoritative tool call forwarded from a Realtime session."""

    _require_active_voice_session(voice_session)
    arguments = arguments or {}
    normalized_name = name.strip()

    if normalized_name == "sign_lab_orders":
        from api.v1.endpoints._lab_order_submission import submit_lab_orders_for_simulation

        raw_orders = arguments.get("orders") or arguments.get("submitted_orders") or []
        if not isinstance(raw_orders, list):
            raise HttpError(400, "orders must be a list")
        result = submit_lab_orders_for_simulation(
            simulation=voice_session.simulation,
            raw_orders=[str(order) for order in raw_orders],
            correlation_id=correlation_id,
        )
        return {
            "name": normalized_name,
            "output": result.model_dump(mode="json"),
        }

    from apps.simcore.tools import get_tool

    tool = get_tool(normalized_name)
    if tool is None:
        raise HttpError(404, f"Voice tool not found: {normalized_name}")

    output = tool(voice_session.simulation).to_dict()
    return {
        "name": normalized_name,
        "output": json.loads(json.dumps(output, default=str)),
    }


def cached_voice_tool_call_result(
    *,
    voice_session: VoiceSession,
    tool_call_id: str,
) -> dict[str, Any] | None:
    """Return a cached tool-call result for duplicate provider events."""

    provider_metadata = voice_session.provider_metadata or {}
    cached_results = provider_metadata.get("tool_call_results")
    if not isinstance(cached_results, dict):
        return None
    cached = cached_results.get(tool_call_id)
    return cached if isinstance(cached, dict) else None


def record_voice_tool_call_result(
    *,
    voice_session: VoiceSession,
    tool_call_id: str,
    result: dict[str, Any],
) -> None:
    """Cache a completed tool-call result on the VoiceSession."""

    provider_metadata = dict(voice_session.provider_metadata or {})
    cached_results = provider_metadata.get("tool_call_results")
    if not isinstance(cached_results, dict):
        cached_results = {}
    cached_results[tool_call_id] = result
    if len(cached_results) > 50:
        cached_results = dict(list(cached_results.items())[-50:])
    provider_metadata["tool_call_results"] = cached_results
    voice_session.provider_metadata = provider_metadata
    voice_session.save(update_fields=["provider_metadata", "updated_at"])
