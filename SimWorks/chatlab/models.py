# chatlab/models.py
import logging

from channels.db import database_sync_to_async
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from simai.models import Response
from simcore.models import BaseSession
from simcore.models import Simulation
from simcore.models import SimulationImage

logger = logging.getLogger(__name__)


class RoleChoices(models.TextChoices):
    USER = "U", _("user")
    ASSISTANT = "A", _("assistant")


class ChatSession(BaseSession):
    """
    Represents a session within ChatLab that extends a shared Simulation instance.
    Additional chat-specific behaviors or fields can be added here.
    """

    pass


class Message(models.Model):

    class MessageType(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        FILE = "file", "File"
        SYSTEM = "system", "System"

    timestamp = models.DateTimeField(auto_now_add=True)

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="messages"
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
        SimulationImage, through="MessageMediaLink", related_name="messages", blank=True
    )

    # UX/Status enhancements
    is_from_ai = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)

    order = models.PositiveIntegerField(editable=False, null=True, blank=True)
    responsev1 = models.ForeignKey(
        "simai.Response",
        on_delete=models.CASCADE,
        verbose_name="OpenAI Response",
        related_name="messages",
        null=True,
        blank=True,
    )
    response = models.ForeignKey(
        "simcore.AIResponse",
        on_delete=models.CASCADE,
        verbose_name="AI Response",
        related_name="messages",
        null=True,
        blank=True,
    )
    provider_response_id = models.CharField(null=True, blank=True, max_length=255)
    display_name = models.CharField(max_length=100, blank=True)

    # TODO deprecated -- remove before v0.8.0
    @property
    def openai_id(self):
        """Deprecated. Use provider_response_id instead."""
        logger.warning(
            "provider_id is deprecated. Use provider_response_id instead.",
            DeprecationWarning,
        )
        return self.response.id if self.response else None

    @property
    def has_media(self):
        return self.media.exists()

    def set_provider_resp_id(self, id):
        self.provider_response_id = id
        self.save(update_fields=["provider_response_id"])

    # TODO deprecated -- remove before v0.8.0
    def set_openai_id(self, openai_id):
        logger.warning(
            "set_openai_id is deprecated. Use set_provider_resp_id instead.",
            DeprecationWarning,
        )
        self.set_provider_resp_id(openai_id)

    def get_previous_openai_id(self) -> str or None:
        """Return most recent OpenAI response_ID in current simulation"""
        previous_message = (
            Message.objects.filter(
                simulation=self.simulation,
                order__lt=self.order,
                role=RoleChoices.ASSISTANT,  # Only consider ASSISTANT messages
                openai_id__isnull=False,  # That have an provider_response_id set
            )
            .order_by("-order")
            .first()
        )
        return previous_message.provider_response_id if previous_message else None

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

    def has_media(self):
        return self.media.exists()

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if self.order is None:
            last_message = (
                Message.objects.filter(simulation=self.simulation)
                .order_by("-order")
                .first()
            )
            self.order = (
                last_message.order + 1
                if last_message and last_message.order is not None
                else 1
            )
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ("simulation", "order")
        ordering = ["timestamp"]

    def __str__(self):
        return f"ChatLab Sim#{self.simulation.pk} {self.get_message_type_display()} by {self.sender} at {self.timestamp:%H:%M:%S}"


class MessageMediaLink(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    message = models.ForeignKey("chatlab.Message", on_delete=models.CASCADE)
    media = models.ForeignKey("simcore.SimulationImage", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("message", "media")
