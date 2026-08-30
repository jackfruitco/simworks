"""VoiceLab session broker services for ChatLab-backed simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
import httpx
from ninja.errors import HttpError

from apps.chatlab.ai.context import build_patient_runtime_context_sync
from apps.chatlab.ai.conversations import (
    ProviderConversationError,
    sync_voice_session_to_provider,
)
from apps.chatlab.ai.instructions import render_voice_patient_instructions
from apps.chatlab.media_payloads import build_chat_message_event_payload
from apps.chatlab.models import (
    Message,
    RoleChoices,
    VoiceSession,
    VoiceToolCall,
    VoiceTranscriptReceipt,
)
from apps.common.outbox import enqueue_event_sync, event_types as outbox_events, poke_drain_sync
from apps.common.utils.accounts import get_or_create_system_user
from apps.simcore.models import Simulation
from config.logging import get_logger
from orchestrai.utils.env_utils import get_api_key

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
    calls_url: str | None = None
    websocket_url: str | None = None
    expires_at: datetime | None = None
    provider_session_id: str = ""
    provider_metadata: dict[str, Any] | None = None
    bootstrap_items: list[dict[str, Any]] | None = None


def default_realtime_model() -> str:
    return getattr(settings, "VOICELAB_REALTIME_MODEL", "gpt-realtime-2.1")


def default_voice_name() -> str:
    return getattr(settings, "VOICELAB_REALTIME_VOICE", "marin")


def default_transcription_model() -> str:
    return getattr(settings, "VOICELAB_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")


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


def realtime_websocket_url() -> str:
    return getattr(
        settings,
        "VOICELAB_OPENAI_WEBSOCKET_URL",
        "wss://api.openai.com/v1/realtime",
    )


def _openai_realtime_api_key() -> str | None:
    return getattr(settings, "OPENAI_API_KEY", None) or get_api_key("openai")


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


def build_realtime_bootstrap_items(conversation) -> list[dict[str, Any]]:
    """Build ordered Realtime input items from canonical MedSim text messages.

    The default is the complete current text history. Deployments that need an
    explicit context budget may set ``VOICELAB_BOOTSTRAP_MAX_CHARS``; selection
    then remains deterministic and is surfaced to the client as a system item.
    """

    messages = list(
        Message.objects.filter(
            simulation_id=conversation.simulation_id,
            conversation_id=conversation.pk,
            is_deleted=False,
            message_type=Message.MessageType.TEXT,
        )
        .exclude(content__isnull=True)
        .exclude(content="")
        .order_by("pk")
    )
    max_chars = max(0, int(getattr(settings, "VOICELAB_BOOTSTRAP_MAX_CHARS", 0)))
    selected = messages
    omitted = 0
    if max_chars:
        total = 0
        selected = []
        for message in reversed(messages):
            content = " ".join(str(message.content or "").split())
            if selected and total + len(content) > max_chars:
                break
            selected.append(message)
            total += len(content)
        selected.reverse()
        omitted = len(messages) - len(selected)

    items: list[dict[str, Any]] = []
    if omitted:
        items.append(
            {
                "type": "message",
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"{omitted} earlier canonical MedSim messages are omitted from this "
                            "voice bootstrap; use only the messages that follow."
                        ),
                    }
                ],
            }
        )
    for message in selected:
        items.append(
            {
                "type": "message",
                "role": "assistant" if message.role == RoleChoices.ASSISTANT else "user",
                "content": [{"type": "input_text", "text": str(message.content or "")}],
            }
        )
    return items


def build_realtime_session_config(
    *,
    simulation: Simulation,
    conversation,
    model: str,
    voice: str,
) -> dict[str, Any]:
    """Build the provider session config sent when minting an ephemeral secret."""

    runtime_context = build_patient_runtime_context_sync(
        simulation=simulation,
        conversation=conversation,
    )
    instructions = render_voice_patient_instructions(runtime_context)
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
    """Mint ephemeral OpenAI Realtime client secrets for iOS voice sessions."""

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
        api_key = _openai_realtime_api_key()
        if not api_key:
            raise VoiceProviderConfigurationError(
                "OpenAI Realtime voice provider is not configured"
            )
        supported_transports = {
            VoiceSession.Transport.WEBRTC,
            VoiceSession.Transport.WEBSOCKET,
        }
        if transport not in supported_transports:
            raise VoiceProviderConfigurationError("Requested voice transport is not supported")

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
            calls_url=(
                realtime_calls_url() if transport == VoiceSession.Transport.WEBRTC else None
            ),
            websocket_url=(
                realtime_websocket_url() if transport == VoiceSession.Transport.WEBSOCKET else None
            ),
            expires_at=expires_at,
            provider_session_id=provider_session_id,
            provider_metadata=_redact_secret_payload(payload),
            bootstrap_items=build_realtime_bootstrap_items(conversation),
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


def _normalize_idempotency_key(idempotency_key: str | None) -> str:
    return (idempotency_key or "").strip()


def _ensure_voice_start_matches(
    voice_session: VoiceSession,
    *,
    conversation,
    transport: str,
    model: str,
    voice: str,
) -> None:
    if (
        voice_session.conversation_id != conversation.pk
        or voice_session.transport != transport
        or voice_session.model_name != model
        or voice_session.voice_name != voice
    ):
        raise HttpError(
            409,
            "Voice session idempotency key was already used with different parameters",
        )
    if voice_session.status == VoiceSession.Status.ENDED:
        raise HttpError(
            409,
            "Voice session idempotency key references an ended session",
        )


def create_voice_session(
    *,
    user,
    simulation: Simulation,
    conversation,
    transport: str,
    model: str | None,
    voice: str | None,
    idempotency_key: str | None = None,
    client_metadata: dict[str, Any] | None = None,
    broker: OpenAIRealtimeSessionBroker | None = None,
    correlation_id: str | None = None,
) -> tuple[VoiceSession, VoiceSessionStart, bool]:
    """Create a VoiceSession and return provider connection material."""

    selected_model = model or default_realtime_model()
    selected_voice = voice or default_voice_name()
    normalized_key = _normalize_idempotency_key(idempotency_key)
    broker = broker or OpenAIRealtimeSessionBroker()
    created = False

    try:
        with transaction.atomic():
            voice_session = None
            if normalized_key:
                voice_session = (
                    VoiceSession.objects.select_for_update()
                    .filter(
                        simulation=simulation,
                        created_by=user,
                        client_idempotency_key=normalized_key,
                    )
                    .first()
                )
                if voice_session:
                    _ensure_voice_start_matches(
                        voice_session,
                        conversation=conversation,
                        transport=transport,
                        model=selected_model,
                        voice=selected_voice,
                    )

            if voice_session is None:
                voice_session = VoiceSession.objects.create(
                    simulation=simulation,
                    conversation=conversation,
                    created_by=user,
                    status=VoiceSession.Status.CONFIGURING,
                    transport=transport,
                    model_name=selected_model,
                    voice_name=selected_voice,
                    client_idempotency_key=normalized_key,
                    client_metadata=client_metadata or {},
                    responses_sync_cursor=conversation.provider_sync_cursor,
                )
                created = True
    except IntegrityError:
        if not normalized_key:
            raise
        with transaction.atomic():
            voice_session = (
                VoiceSession.objects.select_for_update()
                .filter(
                    simulation=simulation,
                    created_by=user,
                    client_idempotency_key=normalized_key,
                )
                .get()
            )
            _ensure_voice_start_matches(
                voice_session,
                conversation=conversation,
                transport=transport,
                model=selected_model,
                voice=selected_voice,
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
    voice_session.last_error_code = ""
    voice_session.last_error_text = ""
    voice_session.save(
        update_fields=[
            "status",
            "expires_at",
            "provider_session_id",
            "provider_metadata",
            "last_error_code",
            "last_error_text",
            "updated_at",
        ]
    )
    _emit_voice_session_event(
        voice_session,
        event_type=outbox_events.VOICE_SESSION_CREATED,
        correlation_id=correlation_id,
    )
    return voice_session, start, created


def end_voice_session(
    *,
    voice_session: VoiceSession,
    correlation_id: str | None = None,
) -> VoiceSession:
    """Mark a live voice session ended and emit a durable lifecycle event."""

    if voice_session.status == VoiceSession.Status.ENDED:
        return voice_session
    try:
        sync_voice_session_to_provider(voice_session)
    except ProviderConversationError:
        # Ending the transport must remain possible when the provider is down;
        # the durable pending marker lets the next text boundary retry sync.
        logger.warning(
            "voicelab.responses_sync_pending voice_session=%s",
            voice_session.pk,
            exc_info=True,
        )
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
            VoiceTranscriptReceipt.objects.select_related(
                "message__conversation__conversation_type",
            )
            .filter(voice_session=voice_session, provider_message_id=provider_id)
            .first()
        )
        if existing:
            return existing.message, False

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

    try:
        with transaction.atomic():
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
            if provider_id:
                VoiceTranscriptReceipt.objects.create(
                    voice_session=voice_session,
                    provider_message_id=provider_id,
                    message=message,
                )
    except IntegrityError:
        if not provider_id:
            raise
        existing = (
            VoiceTranscriptReceipt.objects.select_related(
                "message__conversation__conversation_type",
            )
            .filter(voice_session=voice_session, provider_message_id=provider_id)
            .first()
        )
        if existing:
            return existing.message, False
        raise

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


def _ensure_voice_tool_call_matches(
    record: VoiceToolCall,
    *,
    name: str,
    arguments: dict[str, Any],
) -> None:
    if record.name != name or record.arguments != arguments:
        raise HttpError(
            409,
            "Voice tool call ID was already used with different parameters",
        )


def execute_voice_tool_call_once(
    *,
    voice_session: VoiceSession,
    tool_call_id: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Execute a voice tool call once, returning a durable result on duplicates."""

    _require_active_voice_session(voice_session)
    normalized_call_id = tool_call_id.strip()
    normalized_name = name.strip()
    normalized_arguments = arguments or {}
    if not normalized_call_id:
        raise HttpError(400, "tool_call_id must contain non-empty text")
    if not normalized_name:
        raise HttpError(400, "name must contain non-empty text")

    try:
        with transaction.atomic():
            record = (
                VoiceToolCall.objects.select_for_update()
                .filter(voice_session=voice_session, tool_call_id=normalized_call_id)
                .first()
            )
            if record:
                _ensure_voice_tool_call_matches(
                    record,
                    name=normalized_name,
                    arguments=normalized_arguments,
                )
                if record.status == VoiceToolCall.Status.COMPLETED:
                    return {
                        "name": record.name,
                        "output": record.output,
                    }, False
                if record.status == VoiceToolCall.Status.RUNNING:
                    raise HttpError(409, "Voice tool call is already in progress")
                record.status = VoiceToolCall.Status.RUNNING
                record.last_error_text = ""
                record.save(update_fields=["status", "last_error_text", "updated_at"])
            else:
                record = VoiceToolCall.objects.create(
                    voice_session=voice_session,
                    tool_call_id=normalized_call_id,
                    name=normalized_name,
                    arguments=normalized_arguments,
                    status=VoiceToolCall.Status.RUNNING,
                )

            execution_error = None
            result = None
            try:
                result = execute_voice_tool_call(
                    voice_session=voice_session,
                    name=normalized_name,
                    arguments=normalized_arguments,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                execution_error = exc
                record.status = VoiceToolCall.Status.FAILED
                record.last_error_text = str(exc)
                record.save(
                    update_fields=["status", "last_error_text", "updated_at"],
                )
            else:
                record.name = result["name"]
                record.output = result["output"]
                record.status = VoiceToolCall.Status.COMPLETED
                record.last_error_text = ""
                record.save(
                    update_fields=[
                        "name",
                        "output",
                        "status",
                        "last_error_text",
                        "updated_at",
                    ],
                )
        if execution_error:
            raise execution_error
    except IntegrityError as err:
        record = (
            VoiceToolCall.objects.select_related("voice_session")
            .filter(voice_session=voice_session, tool_call_id=normalized_call_id)
            .get()
        )
        _ensure_voice_tool_call_matches(
            record,
            name=normalized_name,
            arguments=normalized_arguments,
        )
        if record.status == VoiceToolCall.Status.COMPLETED:
            return {
                "name": record.name,
                "output": record.output,
            }, False
        raise HttpError(409, "Voice tool call is already in progress") from err

    if result is None:
        raise HttpError(500, "Voice tool call did not return a result")
    return result, True
