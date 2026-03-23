# chatlab/models.py
from typing import ClassVar

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
            )
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
