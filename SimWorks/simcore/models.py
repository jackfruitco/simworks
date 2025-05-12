# simcore/models.py
import logging
import os
import uuid
from datetime import timedelta

from autoslug import AutoSlugField
from django.conf import settings
from django.db import models
from django.db.models import QuerySet
from django.utils.timezone import now
from imagekit.models import ImageSpecField
from pilkit.processors import Thumbnail

from simai.models import Prompt
from simcore.utils import randomize_display_name

logger = logging.getLogger(__name__)

def get_image_path(instance, filename):
    ext = os.path.splitext(filename)[1] or ".webp"
    unique_id = instance.uuid
    return f"images/simulation/{instance.simulation.pk}/{unique_id}{ext}"

def slug_source(instance):
    return instance.description or str(instance.uuid)

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
    def create(self, *, user=None, prompt=None, lab=None, is_template=False, **kwargs):
        from simai.prompts import build_prompt
        if not user and not is_template:
            raise ValueError("Simulation must have a user unless marked as template.")

        # Extract modifiers if provided
        modifiers = kwargs.pop("modifiers", [])

        if not prompt and user and lab:
            role = getattr(user, "role", None)
            prompt = build_prompt(user=user, role=role, lab=lab, modifiers=modifiers)

        if not prompt:
            raise ValueError("Prompt must be provided if no user/lab fallback is available.")

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
    prompt = models.JSONField(
        help_text="The prompt to use as AI instructions",
    )

    # description = models.TextField(blank=True, null=True)
    diagnosis = models.CharField(max_length=255, blank=True, null=True)
    chief_complaint = models.CharField(max_length=255, blank=True, null=True)

    sim_patient_full_name = models.CharField(max_length=100, blank=True)
    sim_patient_display_name = models.CharField(max_length=100, blank=True)

    def history(self, _format=None) -> list:
        """
        Returns combined simulation history from all registered apps.
        """
        from simcore.history_registry import get_sim_history
        return get_sim_history(self, _format)

    @property
    def sim_patient_initials(self):
        parts = self.sim_patient_display_name.strip().split()
        if not parts:
            return "Unk"

        if len(parts) == 1:
            return parts[0][0].upper()

        # Use first and last word initials if more than one word
        return f"{parts[0][0].upper()}{parts[-1][0].upper()}"

    @property
    def is_complete(self) -> bool:
        """Returns True if simulation has ended, either manually or due to timeout."""
        if self.end_timestamp:
            return True
        if self.time_limit:
            return now() > self.start_timestamp + self.time_limit
        return False

    @property
    def is_in_progress(self) -> bool:
        """Returns True only if simulation is actively in progress."""
        return not self.is_complete

    @property
    def is_ended(self) -> bool:
        """Alias for is_complete to preserve compatibility."""
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

    @property
    def start_timestamp_ms(self):
        if self.start_timestamp:
            return int(self.start_timestamp.timestamp() * 1000)
        return 0

    @property
    def end_timestamp_ms(self):
        if self.end_timestamp:
            return int(self.end_timestamp.timestamp() * 1000)
        return 0

    @property
    def time_limit_ms(self):
        if self.time_limit:
            return int(self.time_limit.total_seconds() * 1000)
        return 0

    def end(self):
        self.end_timestamp = now()
        self.save()
        self.generate_feedback()

    def generate_feedback(self):
        from asgiref.sync import async_to_sync
        from simai.async_client import AsyncOpenAIService

        service = AsyncOpenAIService()
        async_to_sync(service.generate_simulation_feedback)(self)

    def calculate_metadata_checksum(self) -> str:
        from hashlib import sha256

        # Always order by attribute and key for stable checksum
        entries = self.metadata.order_by('attribute', 'key').values_list('attribute', 'key', 'value')
        data = "|".join(f"{attr}:{key}:{value}" for attr, key, value in entries)
        return sha256(data.encode('utf-8')).hexdigest()

    @classmethod
    def create_with_default_prompt(cls, user, lab="chatlab", **kwargs):
        """
        Create a Simulation with a default prompt based on the user role and lab.
        """
        from simai.prompts import build_prompt

        prompt = build_prompt(user=user, role=user.role, lab=lab)

        return cls.objects.create(user=user, prompt=prompt, **kwargs)

    @property
    def formatted_patient_history(self):
        raw = self.metadata.filter(attribute="patient history")
        return SimulationMetadata.format_patient_history(raw)

    def save(self, *args, **kwargs):
        from simai.prompts import build_prompt
        # Ensure prompt is set based on user.role if not already provided
        if not self.prompt:
            if not self.user:
                raise ValueError("Cannot assign default prompt without a user.")
            # self.prompt = get_or_create_prompt(app_label="chatlab", user=self.user, role=getattr(self.user, "role", None))
            # self.prompt = build_prompt(lab="chatlab", user=self.user, role=getattr(self.user, "role", None))
            self.prompt = build_prompt(lab="chatlab", user=self.user)

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
        base = f"Simulation {self.pk}"
        if self.diagnosis:
            base = base + f": {self.chief_complaint}"
        return base


class SimulationMetadata(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="metadata"
    )
    key = models.CharField(blank=False, null=False, max_length=255)
    attribute = models.CharField(blank=False, null=False, max_length=64)
    value = models.CharField(blank=False, null=False, max_length=2000)

    @classmethod
    def format_patient_history(cls, history_metadata: QuerySet) -> list[dict]:
        from collections import defaultdict

        grouped = defaultdict(dict)
        for entry in history_metadata:
            key = entry.key
            value = entry.value
            prefix, field = key.rsplit(" ", 1)
            grouped[prefix][field] = value
        logger.debug(f"grouped: {grouped}")

        formatted = [
            {"key": prefix, "value": "{diagnosis} ({resolved}, {duration})".format(
                diagnosis=data.get("diagnosis", "Unknown").title(),
                resolved=data.get("resolved", "Unknown"),
                duration=data.get("duration", "Unknown")
            )}
            for prefix, data in grouped.items()
        ]
        logger.debug(f"formatted: {formatted}")

        return formatted

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


class SimulationImage(models.Model):
    """Store image for specified simulation."""
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    modified_at = models.DateTimeField(auto_now=True, editable=False)

    simulation = models.ForeignKey(
        Simulation,
        on_delete=models.CASCADE,
        related_name="images"
    )

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=True,
        help_text="Unique identifier for this image"
    )

    description = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="3-5 words describing the image",
    )

    slug = AutoSlugField(
        populate_from=slug_source,
        unique_with="simulation",
        always_update=True,
    )

    original = models.ImageField(
        upload_to=get_image_path,
        verbose_name="image",
        height_field="original_height",
        width_field="original_width",
    )

    original_height = models.PositiveIntegerField(
        editable=False,
        blank=True,
        null=True,
    )

    original_width = models.PositiveIntegerField(
        editable=False,
        blank=True,
        null=True,
    )

    thumbnail = ImageSpecField(
        source="original",
        processors=[Thumbnail(width=300, height=300, crop=False)],
        format="WEBP",
        options={"quality": 80},
    )

    logo = ImageSpecField(
        source="original",
        processors=[Thumbnail(width=600, height=600, crop=False)],
        format="WEBP",
        options={"quality": 80},
    )

    def __str__(self):
        return f"Image for Sim#{self.simulation.pk} ({self.slug})"