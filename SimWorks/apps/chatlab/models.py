# chatlab/models.py
from typing import ClassVar
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.common.models import PersistModel
from apps.simcore.models import BaseSession, Simulation, SimulationImage


class RoleChoices(models.TextChoices):
    USER = "U", _("user")
    ASSISTANT = "A", _("assistant")


class ChatSession(BaseSession):
    """
    Represents a session within ChatLab that extends a shared Simulation instance.
    Additional chat-specific behaviors or fields can be added here.
    """


class VoiceSession(PersistModel):
    """Provider-backed live voice session for a ChatLab simulation."""

    class Status(models.TextChoices):
        CONFIGURING = "configuring", "Configuring"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        FAILED = "failed", "Failed"

    class Transport(models.TextChoices):
        WEBRTC = "webrtc", "WebRTC"
        WEBSOCKET = "websocket", "WebSocket"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    simulation = models.ForeignKey(
        Simulation,
        on_delete=models.CASCADE,
        related_name="voice_sessions",
    )
    conversation = models.ForeignKey(
        "simcore.Conversation",
        on_delete=models.CASCADE,
        related_name="voice_sessions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chatlab_voice_sessions",
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CONFIGURING,
        db_index=True,
    )
    transport = models.CharField(
        max_length=16,
        choices=Transport.choices,
        default=Transport.WEBRTC,
    )
    provider = models.CharField(max_length=32, default="openai")
    provider_session_id = models.CharField(max_length=255, blank=True, default="")
    model_name = models.CharField(max_length=100, blank=True, default="")
    voice_name = models.CharField(max_length=100, blank=True, default="")
    client_idempotency_key = models.CharField(max_length=255, blank=True, default="")
    client_metadata = models.JSONField(blank=True, default=dict)
    provider_metadata = models.JSONField(blank=True, default=dict)
    responses_sync_cursor = models.PositiveBigIntegerField(
        blank=True,
        null=True,
        help_text="Canonical Message ID known to be in Responses when this voice session branched.",
    )
    responses_sync_status = models.CharField(
        max_length=16,
        choices=[
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("failed", "Failed"),
        ],
        default="pending",
        db_index=True,
    )
    responses_sync_error = models.TextField(blank=True, default="")
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    last_error_text = models.TextField(blank=True, default="")

    class Meta:
        ordering: ClassVar = ["-created_at", "-pk"]
        indexes: ClassVar = [
            models.Index(
                fields=["simulation", "status", "created_at"],
                name="chatlab_voice_sim_status_idx",
            ),
            models.Index(
                fields=["created_by", "created_at"],
                name="chatlab_voice_actor_idx",
            ),
            models.Index(
                fields=["created_by", "simulation", "client_idempotency_key"],
                name="chatlab_voice_idem_idx",
            ),
        ]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["created_by", "simulation", "client_idempotency_key"],
                condition=Q(client_idempotency_key__gt=""),
                name="chatlab_unique_voice_start_idem",
            ),
        ]

    def __str__(self):
        return f"ChatLab VoiceSession#{self.pk} sim#{self.simulation_id} {self.status}"


class VoiceToolCall(PersistModel):
    """Durable VoiceLab tool-call execution record."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    voice_session = models.ForeignKey(
        VoiceSession,
        on_delete=models.CASCADE,
        related_name="tool_calls",
    )
    tool_call_id = models.CharField(max_length=255)
    name = models.CharField(max_length=100)
    arguments = models.JSONField(blank=True, default=dict)
    output = models.JSONField(blank=True, default=dict)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
    )
    last_error_text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar = ["-created_at", "-pk"]
        indexes: ClassVar = [
            models.Index(
                fields=["voice_session", "status"],
                name="chatlab_voice_tool_status_idx",
            ),
        ]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["voice_session", "tool_call_id"],
                name="chatlab_unique_voice_tool_call",
            ),
        ]

    def __str__(self):
        return f"ChatLab VoiceToolCall#{self.pk} session#{self.voice_session_id} {self.status}"


class VoiceTranscriptReceipt(PersistModel):
    """Durable idempotency receipt for provider transcript events."""

    voice_session = models.ForeignKey(
        VoiceSession,
        on_delete=models.CASCADE,
        related_name="transcript_receipts",
    )
    provider_message_id = models.CharField(max_length=255)
    message = models.ForeignKey(
        "chatlab.Message",
        on_delete=models.CASCADE,
        related_name="voice_transcript_receipts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar = ["-created_at", "-pk"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["voice_session", "provider_message_id"],
                name="chatlab_unique_voice_transcript",
            ),
        ]

    def __str__(self):
        return f"ChatLab VoiceTranscriptReceipt#{self.pk} session#{self.voice_session_id}"


class Message(PersistModel):
    class MessageType(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        FILE = "file", "File"
        SYSTEM = "system", "System"

    class DeliveryStatus(models.TextChoices):
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    timestamp = models.DateTimeField(auto_now_add=True)

    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name="input")
    conversation = models.ForeignKey(
        "simcore.Conversation",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    content = models.TextField(blank=True, null=True)
    role = models.CharField(
        max_length=2,
        choices=RoleChoices.choices,
        default=RoleChoices.USER,
    )

    message_type = models.CharField(
        max_length=16,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )

    # Media
    media = models.ManyToManyField(
        SimulationImage, through="MessageMediaLink", related_name="input", blank=True
    )

    # UX/Status enhancements
    is_from_ai = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    image_requested = models.BooleanField(
        default=False,
        help_text="Whether this message references images/scans that should be generated",
    )
    delivery_status = models.CharField(
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.SENT,
        db_index=True,
    )
    delivery_error_code = models.CharField(max_length=100, blank=True, default="")
    delivery_error_text = models.TextField(blank=True, default="")
    delivery_retryable = models.BooleanField(default=True)
    delivery_retry_count = models.PositiveSmallIntegerField(default=0)

    service_call_attempt = models.ForeignKey(
        "orchestrai_django.ServiceCallAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        help_text="Link to service call attempt that produced this message",
    )
    provider_response_id = models.CharField(null=True, blank=True, max_length=255)
    display_name = models.CharField(max_length=100, blank=True)
    source_message = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_messages",
        help_text="Source message this message was derived from (e.g., generated image).",
    )

    def set_provider_resp_id(self, id_):
        self.provider_response_id = id_
        self.save(update_fields=["provider_response_id"])

    def get_openai_input(self, request=None) -> dict:
        """Return dict formatted for OpenAI Responses API input.

        For image-type messages, includes image_url content blocks so the LLM
        receives visual context from previously generated images.  The caller
        must supply *request* (or ensure images are served at absolute URLs) for
        the URLs to be resolvable by the provider.
        """
        if self.message_type == self.MessageType.IMAGE:
            from apps.chatlab.media_payloads import build_message_media_payload

            media_payload = build_message_media_payload(self, request=request)
            content = [
                {"type": "input_image", "image_url": item["original_url"]}
                for item in media_payload.get("media_list", [])
                if item.get("original_url")
            ]
            if self.content:
                content.append({"type": "input_text", "text": self.content})
            return {
                "role": self.get_role_display(),
                "content": content if content else self.content,
            }
        return {
            "role": self.get_role_display(),
            "content": self.content,
        }

    def is_media(self):
        return self.message_type in {
            self.MessageType.IMAGE,
            self.MessageType.VIDEO,
            self.MessageType.AUDIO,
            self.MessageType.FILE,
        }

    @property
    def has_media(self):
        return self.media.exists()

    class Meta:
        ordering: ClassVar = ["timestamp"]
        indexes: ClassVar = [
            models.Index(
                fields=["simulation", "timestamp"],
                name="chatlab_msg_sim_ts_idx",
            ),
        ]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["source_message"],
                condition=Q(
                    source_message__isnull=False,
                    message_type="image",
                    is_from_ai=True,
                ),
                name="chatlab_unique_ai_image_per_source_message",
            ),
        ]

    def __str__(self):
        return f"ChatLab Sim#{self.simulation.pk} {self.get_message_type_display()} by {self.sender} at {self.timestamp:%H:%M:%S}"


class MessageMediaLink(PersistModel):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    message = models.ForeignKey("chatlab.Message", on_delete=models.CASCADE)
    media = models.ForeignKey("simcore.SimulationImage", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("message", "media")


class ProviderConversationItem(PersistModel):
    """Idempotency receipt for a canonical message appended to a provider conversation."""

    conversation = models.ForeignKey(
        "simcore.Conversation",
        on_delete=models.CASCADE,
        related_name="provider_items",
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="provider_conversation_items",
    )
    provider_conversation_id = models.CharField(max_length=255)
    provider_item_id = models.CharField(max_length=255)
    item_type = models.CharField(max_length=32, default="message")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar = ["message_id", "pk"]
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["conversation", "message", "provider_conversation_id"],
                name="chatlab_unique_provider_message_sync",
            ),
            models.UniqueConstraint(
                fields=["provider_conversation_id", "provider_item_id"],
                name="chatlab_unique_provider_item_id",
            ),
        ]
