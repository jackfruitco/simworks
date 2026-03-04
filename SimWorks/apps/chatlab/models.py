# chatlab/models.py
from typing import ClassVar

from django.conf import settings
from django.db import models
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
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
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

    def set_provider_resp_id(self, id_):
        self.provider_response_id = id_
        self.save(update_fields=["provider_response_id"])

    def get_openai_input(self) -> dict:
        """Return list formatted for OpenAI Responses API input."""
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

    def __str__(self):
        return f"ChatLab Sim#{self.simulation.pk} {self.get_message_type_display()} by {self.sender} at {self.timestamp:%H:%M:%S}"


class MessageMediaLink(PersistModel):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    message = models.ForeignKey("chatlab.Message", on_delete=models.CASCADE)
    media = models.ForeignKey("simcore.SimulationImage", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("message", "media")
