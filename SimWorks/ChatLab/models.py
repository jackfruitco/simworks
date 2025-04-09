import json
import logging
from datetime import datetime
from datetime import timedelta
from hashlib import sha256

from core.utils import randomize_display_name
from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from .constants import DEFAULT_PROMPT_CONTENT
from .constants import DEFAULT_PROMPT_TITLE

logger = logging.getLogger(__name__)


def get_default_prompt():
    """"""
    prompt, created = Prompt.objects.get_or_create(
        title=DEFAULT_PROMPT_TITLE, defaults={"content": DEFAULT_PROMPT_CONTENT}
    )
    return prompt.id


class RoleChoices(models.TextChoices):
    USER = "U", _("user")
    ASSISTANT = "A", _("assistant")


class Prompt(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_prompts",
    )
    modified_at = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_prompts",
    )
    is_archived = models.BooleanField(default=False)

    title = models.CharField(max_length=100)
    content = models.TextField(help_text="The scenario prompt sent to OpenAI.")

    @property
    def is_active(self) -> bool:
        return not self.is_archived

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Update modification fields if object already exists."""
        if self.pk is not None:
            self.modified_at = now()
            if hasattr(self, "_modified_by"):
                self.modified_by = self._modified_by

        super().save(*args, **kwargs)

    def set_modified_by(self, user):
        self._modified_by = user


class Simulation(models.Model):
    start = models.DateTimeField(auto_now_add=True)
    end = models.DateTimeField(blank=True, null=True)
    time_limit = models.DurationField(
        blank=True, null=True, help_text="Optional max duration for this simulation"
    )
    prompt = models.ForeignKey(
        Prompt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=get_default_prompt,
        help_text=_("The prompt to use as AI instructions."),
    )

    description = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    metadata_checksum = models.CharField(max_length=64, blank=True, null=True)

    sim_patient_full_name = models.CharField(max_length=100, blank=True)
    sim_patient_display_name = models.CharField(max_length=100, blank=True)

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
        return self.end is None or self.end < datetime.now()

    @property
    def is_complete(self) -> bool:
        """Return if simulation has already completed."""
        return self.end is not None or (
            self.time_limit and now() > self.start + self.time_limit
        )

    @property
    def is_ended(self):
        return self.is_complete

    @property
    def is_timed_out(self):
        return bool(self.time_limit and now() > self.start + self.time_limit)

    @property
    def length(self) -> timedelta or None:
        """Return timedelta from simulation start to finish, or None if not ended"""
        if self.start and self.end:
            return self.end - self.start
        return None

    @property
    def history(self) -> list:
        """Return message history for simulation"""
        _history = []
        messages = Message.objects.filter(simulation=self.pk, order__gt=0).order_by(
            "-order"
        )
        for message in messages:
            _history.append(
                {"role": message.get_role_display(), "content": message.content}
            )
        return _history

    def calculate_metadata_checksum(self) -> str:
        # Get sorted list of (key, value) pairs
        data = list(self.metadata.values_list("key", "value").order_by("key"))
        encoded = json.dumps(data)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        updating_name = False

        if self.pk:
            old = Simulation.objects.get(pk=self.pk)
            updating_name = old.sim_patient_full_name != self.sim_patient_full_name
        else:
            updating_name = bool(self.sim_patient_full_name)

        if updating_name:
            self.sim_patient_display_name = randomize_display_name(
                self.sim_patient_full_name
            )

        super().save(*args, **kwargs)

        if self.time_limit:
            run_time = f" with max run time set to {self.time_limit}"
        else:
            run_time = f" with no max run time"
        logger.info(
            f"New Simulation: Sim #{self.pk} created for {self.user.username}{run_time}"
        )

    def __str__(self) -> str:
        if self.description:
            return f"ChatLab Sim #{self.pk}: {self.description}"
        else:
            return f"ChatLab Sim #{self.pk}"

    def get_or_assign_prompt(self):
        """
        Return the current prompt assigned to the simulation. If none exists,
        assign the system default prompt and return it.
        """
        if not self.prompt:
            self.prompt_id = get_default_prompt()
            self.save(update_fields=["prompt"])
        return self.prompt


class SimulationMetafield(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="metadata"
    )
    key = models.TextField(blank=False, null=False)
    value = models.TextField(blank=False, null=False)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        self.simulation.metadata_checksum = (
            self.simulation.calculate_metadata_checksum()
        )
        self.simulation.save(update_fields=["metadata_checksum"])
        logger.info(
            "[SimulationMetafield.save] %s metafield: %s for SIM #%s (ID: %s)",
            "New" if is_new else "Modified",
            self.key.lower(),
            self.simulation.id,
            self.id,
        )

    def __str__(self):
        return f"SIM #{self.simulation.id} Metafield: {self.key.title()} " f""


class Message(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)

    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField(blank=True, null=True)
    role = models.CharField(
        max_length=2,
        choices=RoleChoices.choices,
        default=RoleChoices.USER,
    )

    is_read = models.BooleanField(default=False)
    order = models.PositiveIntegerField(editable=False, null=True, blank=True)
    openai_id = models.CharField(null=True, blank=True, max_length=255)
    display_name = models.CharField(max_length=100, blank=True)

    def set_openai_id(self, openai_id):
        self.openai_id = openai_id
        self.save(update_fields=["openai_id"])

    def get_previous_openai_id(self) -> str or None:
        """Return most recent OpenAI response_ID in current simulation"""
        previous_message = (
            Message.objects.filter(
                simulation=self.simulation,
                order__lt=self.order,
                role=RoleChoices.ASSISTANT,  # Only consider ASSISTANT messages
                openai_id__isnull=False,  # That have an openai_id set
            )
            .order_by("-order")
            .first()
        )
        return previous_message.openai_id if previous_message else None

    def get_openai_input(self) -> list:
        """Return list formatted for OpenAI Responses API input."""
        return [
            {
                "role": self.get_role_display(),
                "content": self.content,
            }
        ]

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
        logger.info(
            "[Message.save] %s message for ChatLab Sim #%s from %s (ID: %s)",
            "New" if is_new else "Modified",
            self.simulation.pk,
            self.sender.username if self.sender else "System",
            self.pk,
        )

    class Meta:
        unique_together = ("simulation", "order")
        ordering = ["timestamp"]

    def __str__(self) -> str:
        role_label = dict(RoleChoices.choices).get(self.role, self.role)
        return f"ChatLab Sim #{self.simulation.pk} {role_label.capitalize()} Message (ID: {self.pk})"
