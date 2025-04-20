import json
import logging
from datetime import datetime, timedelta
from hashlib import sha256

from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from simcore.utils import randomize_display_name
from simai.models import Prompt
from simai.prompts import get_or_create_prompt

logger = logging.getLogger(__name__)


class BaseSession(models.Model):
    """
    Abstract base model for Lab-specific session tracking tied to a Simulation.

    This model is intended to be subclassed by individual Lab apps
    (e.g., ChatLab, VoiceLab, VidLab) to represent the session context
    associated with a single Simulation instance.

    Purpose:
        - Encapsulate shared session-level fields (e.g., timestamps, notes).
        - Maintain a clean separation of concerns: Simulation logic lives in `simcore`,
          while per-Lab session data is stored in the corresponding app.
        - Enable consistent access patterns and tooling across Labs, while allowing
          each to extend its Session model as needed.

    Example:
        class ChatSession(BaseSession):
            chat_theme = models.CharField(...)
            language_model = models.CharField(...)

    This design supports scalable, modular simulations where each Lab app manages
    its own session concerns without tightly coupling back to core simulation logic.
    """

    simulation = models.OneToOneField(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="session"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        abstract = True


class SimulationManager(models.Manager):
    def create(self, *, user=None, prompt=None, lab_label=None, is_template=False, **kwargs):
        if not user and not is_template:
            raise ValueError("Simulation must have a user unless marked as template.")

        if not prompt and user and lab_label:
            from simai.prompts import get_or_create_prompt
            role = getattr(user, "role", None)
            prompt = get_or_create_prompt(app_label=lab_label, role=role)

        if not prompt:
            raise ValueError("Prompt must be provided if no user/lab_label fallback is available.")

        kwargs["user"] = user
        kwargs["prompt"] = prompt
        return super().create(**kwargs)


class Simulation(models.Model):
    start_timestamp = models.DateTimeField(auto_now_add=True)
    end_timestamp = models.DateTimeField(blank=True, null=True)
    objects = SimulationManager()
    time_limit = models.DurationField(
        blank=True, null=True, help_text="Optional max duration for this simulation"
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    openai_model = models.CharField(blank=True, null=True, max_length=128)
    metadata_checksum = models.CharField(max_length=64, blank=True, null=True)
    prompt = models.ForeignKey(
        Prompt,
        on_delete=models.RESTRICT,
        null=False,
        blank=False,
        help_text=_("The prompt to use as AI instructions."),
    )

    description = models.TextField(blank=True, null=True)
    sim_patient_full_name = models.CharField(max_length=100, blank=True)
    sim_patient_display_name = models.CharField(max_length=100, blank=True)

    @property
    def history(self) -> list:
        """
        Returns combined simulation history from all registered apps.
        """
        from simcore.history_registry import get_sim_history
        return get_sim_history(self)

    @property
    def sim_patient_initials(self):
        parts = self.sim_patient_display_name.strip().split()
        if not parts:
            return "Unk"

        if len(parts) == 1:
            return parts[0][0].upper()

        # Use first and last word initials if more than one word
        return f"{parts[0][0].upper()}{parts[-1][0].upper()}"

    diagnosis = models.TextField(blank=True, null=True, max_length=100)

    @property
    def in_progress(self) -> bool:
        """Return if simulation is in progress"""
        return self.end_timestamp is None or self.end_timestamp < datetime.now()

    @property
    def is_complete(self) -> bool:
        """Return if simulation has already completed."""
        return self.end_timestamp is not None or (
                self.time_limit and now() > self.start_timestamp + self.time_limit
        )

    @property
    def is_ended(self):
        return self.is_complete

    @property
    def is_timed_out(self):
        return bool(self.time_limit and now() > self.start_timestamp + self.time_limit)

    @property
    def length(self) -> timedelta or None:
        """Return timedelta from simulation start_timestamp to finish, or None if not ended"""
        if self.start_timestamp and self.end_timestamp:
            return self.end_timestamp - self.start_timestamp
        return None

    def end(self):
        self.end_timestamp = now()
        self.save()
        self.generate_feedback()

    def generate_feedback(self):
        from asgiref.sync import async_to_sync
        from simai.async_client import AsyncOpenAIChatService

        service = AsyncOpenAIChatService()
        async_to_sync(service.generate_simulation_feedback)(self)

    def calculate_metadata_checksum(self) -> str:
        # Get sorted list of (key, value) pairs
        data = list(self.metadata.values_list("key", "value").order_by("key"))
        encoded = json.dumps(data)
        return sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def create_with_default_prompt(cls, user, app_label="chatlab", **kwargs):
        """
        Create a Simulation with a default prompt based on the user role and app_label.
        """
        from simai.prompts import get_or_create_prompt

        prompt = get_or_create_prompt(app_label=app_label, role=user.role)
        return cls.objects.create(user=user, prompt=prompt, **kwargs)

    def save(self, *args, **kwargs):
        # Ensure prompt is set based on user.role if not already provided
        if not self.prompt:
            if not self.user:
                raise ValueError("Cannot assign default prompt without a user.")
            self.prompt = get_or_create_prompt(app_label="chatlab", role=getattr(self.user, "role", None))

        # Handle display name update if full name is changed
        updating_name = False
        if self.pk:
            old = Simulation.objects.get(pk=self.pk)
            updating_name = old.sim_patient_full_name != self.sim_patient_full_name
        else:
            updating_name = bool(self.sim_patient_full_name)

        if updating_name:
            self.sim_patient_display_name = randomize_display_name(self.sim_patient_full_name)

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        if self.description:
            return f"ChatLab Sim #{self.pk}: {self.description}"
        else:
            return f"ChatLab Sim #{self.pk}"


class SimulationMetadata(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="metadata"
    )
    key = models.CharField(blank=False, null=False, max_length=255)
    attribute = models.CharField(blank=False, null=False, max_length=64)
    value = models.CharField(blank=False, null=False, max_length=2000)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        self.simulation.metadata_checksum = (
            self.simulation.calculate_metadata_checksum()
        )
        self.simulation.save(update_fields=["metadata_checksum"])

    def __str__(self):
        return (
            f"Sim#{self.simulation.id} Metadata ({self.attribute.lower()}): {self.key.title()} "
            f""
        )
