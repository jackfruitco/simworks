# simcore/models.py
import asyncio
from datetime import timedelta
import logging
import mimetypes
import os
import uuid
import warnings

from asgiref.sync import async_to_sync, sync_to_async
from autoslug import AutoSlugField
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models import QuerySet
from django.utils.timezone import now
from imagekit.models import ImageSpecField
from pilkit.processors import Thumbnail
from polymorphic.models import PolymorphicModel

from apps.common.models import PersistModel
from orchestrai_django.components.promptkit import Prompt

from .utils import randomize_display_name

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
        related_name="%(app_label)s_session",
        related_query_name="%(app_label)s_session",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        abstract = True


class ConversationType(models.Model):
    """Reference table for conversation types across all labs.

    Defines the purpose and behavior of a conversation thread within a simulation.
    The ``ai_persona`` field drives AI service dispatch in a data-driven way so that
    adding a new conversation type does not require code changes in the dispatch layer.

    Initial types (seeded via data migration):
    - simulated_patient: Patient chat (locks with simulation)
    - simulated_feedback: Post-sim Stitch debrief
    - simulated_progress_feedback: Cumulative progress review
    - simulation_engine: TrainerLab engine conversation
    - simulated_coach: Future coaching persona
    """

    slug = models.SlugField(max_length=40, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Iconify icon identifier, e.g. 'mdi:robot'",
    )
    ai_persona = models.CharField(
        max_length=40,
        blank=True,
        help_text="AI persona slug for service dispatch (e.g. 'patient', 'stitch')",
    )
    locks_with_simulation = models.BooleanField(
        default=True,
        help_text="If True, conversation becomes read-only when simulation ends",
    )
    available_in = models.JSONField(
        default=list,
        blank=True,
        help_text="Lab apps where this type is available, e.g. ['chatlab', 'trainerlab']",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "slug"]
        verbose_name = "Conversation Type"
        verbose_name_plural = "Conversation Types"

    def __str__(self):
        return self.display_name


class Conversation(PersistModel):
    """A distinct message thread within a simulation.

    Each simulation can have multiple conversations (patient, feedback, coaching, etc.).
    Locking behaviour is determined by the associated ``ConversationType``.
    Created on-demand — the patient conversation is auto-created when a simulation
    starts; other types (e.g. Stitch feedback) are created when the user requests them.
    """

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    conversation_type = models.ForeignKey(
        ConversationType,
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    display_name = models.CharField(max_length=100, blank=True)
    display_initials = models.CharField(max_length=5, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["simulation", "conversation_type"],
                name="idx_conv_sim_type",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["simulation", "conversation_type"],
                name="uniq_conversation_simulation_type",
            ),
        ]
        ordering = ["created_at"]

    @property
    def is_locked(self) -> bool:
        """Conversation is locked when its type says it locks with simulation and sim is done."""
        if self.conversation_type.locks_with_simulation:
            return self.simulation.is_complete
        return False

    def __str__(self):
        return f"{self.conversation_type.display_name} — Sim#{self.simulation_id}"


class Simulation(models.Model):
    """
    Represents a Simulation entity.

    This class models a simulation process, including its configuration, metadata, associated user, and
    runtime details. Simulations can be initiated, processed, and concluded, with support for managing
    AI-based operations and simulation metadata. The class integrates timestamp handling, supports
    duration constraints, and allows interrogation of simulation states such as status, history, and
    patient-related attributes.

    Simulations can be created programmatically through the provided factory methods, enabling both
    synchronous and asynchronous initialization. Instances of this class also expose various properties
    to compute derived attributes, such as simulation length or formatted patient information.

    This entity interacts with other services, such as historical data registries and AI-powered
    feedback generation components, enabling comprehensive simulation lifecycle management.

    :ivar start_timestamp: The timestamp when the simulation started. Automatically set upon creation.
    :type start_timestamp: datetime
    :ivar end_timestamp: The timestamp when the simulation ended. Can be updated after completion or
        upon timeout.
    :type end_timestamp: datetime
    :ivar time_limit: The optional maximum duration for the simulation. If specified, the simulation
        will automatically end after this duration.
    :type time_limit: timedelta
    :ivar user: The user associated with this simulation. It is a foreign key reference to the user
        model.
    :type user: User
    :ivar openai_model: The AI model identifier used for the simulation. Useful if the simulation
        involves AI-driven operations.
    :type openai_model: str
    :ivar metadata_checksum: A checksum for the simulation's metadata, used for verification and
        comparison purposes.
    :type metadata_checksum: str
    :ivar prompt_instruction: AI instruction provided as part of the prompt for the simulation.
    :type prompt_instruction: str
    :ivar prompt_message: AI message provided as part of the prompt. Stored as optional metadata for
        the simulation.
    :type prompt_message: str
    :ivar prompt_meta: Additional metadata for the AI prompt, stored as a structured JSON object.
    :type prompt_meta: dict
    :ivar diagnosis: The diagnosis associated with the simulation, if available.
    :type diagnosis: str
    :ivar chief_complaint: The primary complaint, or reason, motivating the simulation, if specified.
    :type chief_complaint: str
    :ivar sim_patient_full_name: The full name of the simulated patient associated with this simulation.
    :type sim_patient_full_name: str
    :ivar sim_patient_display_name: A display-friendly version of the simulated patient's name.
    :type sim_patient_display_name: str
    """

    class SimulationStatus(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        TIMED_OUT = "timed_out", "Timed Out"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    start_timestamp = models.DateTimeField(auto_now_add=True)
    end_timestamp = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=24,
        choices=SimulationStatus.choices,
        default=SimulationStatus.IN_PROGRESS,
        db_index=True,
    )
    terminal_reason_code = models.CharField(max_length=100, blank=True, default="")
    terminal_reason_text = models.TextField(blank=True, default="")
    terminal_at = models.DateTimeField(blank=True, null=True)
    initial_retry_count = models.PositiveSmallIntegerField(default=0)
    feedback_retry_count = models.PositiveSmallIntegerField(default=0)

    time_limit = models.DurationField(
        blank=True, null=True, help_text="Optional max duration for this simulation"
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    openai_model = models.CharField(blank=True, null=True, max_length=128)
    metadata_checksum = models.CharField(max_length=64, blank=True, null=True)

    # used for new simulations that use prompt_v3 (simcore.ai_v1.promptkit)
    prompt_instruction = models.TextField(
        help_text="The prompt to use as AI instructions",
        default="",
    )
    prompt_message = models.TextField(
        help_text="The prompt to use as AI message",
        blank=True,
        null=True,
    )
    prompt_meta = models.JSONField(
        help_text="The prompt metadata to use as AI message",
        blank=True,
        null=True,
    )

    diagnosis = models.CharField(max_length=255, blank=True, null=True)
    chief_complaint = models.CharField(max_length=255, blank=True, null=True)

    sim_patient_full_name = models.CharField(max_length=100, blank=True)
    sim_patient_display_name = models.CharField(max_length=100, blank=True)

    def history(self, _format=None) -> list:
        """
        Returns combined simulation history from all registered apps.
        """
        from .history_registry import get_sim_history

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
        if self.status in {
            self.SimulationStatus.COMPLETED,
            self.SimulationStatus.TIMED_OUT,
            self.SimulationStatus.FAILED,
            self.SimulationStatus.CANCELED,
        }:
            return True
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
        if self.status == self.SimulationStatus.TIMED_OUT:
            return True
        return bool(
            not self.end_timestamp
            and self.time_limit
            and now() > self.start_timestamp + self.time_limit
        )

    @property
    def is_failed(self) -> bool:
        return self.status == self.SimulationStatus.FAILED

    @property
    def is_canceled(self) -> bool:
        return self.status == self.SimulationStatus.CANCELED

    @property
    def length(self) -> timedelta | None:
        """Return timedelta from apps.simcore start_timestamp to finish, or None if not ended"""
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
    def time_limit_ms(self) -> int:
        if self.time_limit:
            return int(self.time_limit.total_seconds() * 1000)
        return 0

    def _broadcast_state_change(self, retryable: bool | None = None) -> None:
        """Broadcast simulation state transitions via outbox.

        Broadcast is a non-critical side effect and should not break state changes.
        """
        try:
            from apps.common.outbox import enqueue_event_sync, poke_drain_sync

            payload = {
                "simulation_id": self.pk,
                "status": self.status,
                "terminal_reason_code": self.terminal_reason_code or None,
                "terminal_reason_text": self.terminal_reason_text or None,
                "retryable": retryable,
                "terminal_at": self.terminal_at.isoformat() if self.terminal_at else None,
            }
            event = enqueue_event_sync(
                event_type="simulation.state_changed",
                simulation_id=self.pk,
                payload=payload,
            )
            if event:
                poke_drain_sync()
        except Exception:
            logger.exception("Failed to broadcast simulation state change for sim=%s", self.pk)

    def mark_in_progress(self) -> None:
        self.end_timestamp = None
        self.status = self.SimulationStatus.IN_PROGRESS
        self.terminal_reason_code = ""
        self.terminal_reason_text = ""
        self.terminal_at = None
        self.save(
            update_fields=[
                "end_timestamp",
                "status",
                "terminal_reason_code",
                "terminal_reason_text",
                "terminal_at",
            ]
        )
        self._broadcast_state_change(retryable=True)

    def mark_completed(self) -> None:
        timestamp = now()  # type: ignore[assignment]
        self.end_timestamp = timestamp
        self.status = self.SimulationStatus.COMPLETED
        self.terminal_reason_code = ""
        self.terminal_reason_text = ""
        self.terminal_at = timestamp
        self.save(
            update_fields=[
                "end_timestamp",
                "status",
                "terminal_reason_code",
                "terminal_reason_text",
                "terminal_at",
            ]
        )
        self._broadcast_state_change(retryable=False)

    def mark_timed_out(self) -> None:
        timestamp = now()  # type: ignore[assignment]
        self.end_timestamp = timestamp
        self.status = self.SimulationStatus.TIMED_OUT
        self.terminal_reason_code = "timed_out"
        self.terminal_reason_text = "Simulation timed out."
        self.terminal_at = timestamp
        self.save(
            update_fields=[
                "end_timestamp",
                "status",
                "terminal_reason_code",
                "terminal_reason_text",
                "terminal_at",
            ]
        )
        self._broadcast_state_change(retryable=False)

    def mark_failed(
        self,
        *,
        reason_code: str,
        reason_text: str,
        retryable: bool = True,
    ) -> None:
        timestamp = now()  # type: ignore[assignment]
        self.end_timestamp = timestamp
        self.status = self.SimulationStatus.FAILED
        self.terminal_reason_code = reason_code
        self.terminal_reason_text = reason_text
        self.terminal_at = timestamp
        self.save(
            update_fields=[
                "end_timestamp",
                "status",
                "terminal_reason_code",
                "terminal_reason_text",
                "terminal_at",
            ]
        )
        self._broadcast_state_change(retryable=retryable)

    def mark_canceled(
        self, *, reason_code: str = "canceled_by_user", reason_text: str = "Canceled by user"
    ) -> None:
        timestamp = now()  # type: ignore[assignment]
        self.end_timestamp = timestamp
        self.status = self.SimulationStatus.CANCELED
        self.terminal_reason_code = reason_code
        self.terminal_reason_text = reason_text
        self.terminal_at = timestamp
        self.save(
            update_fields=[
                "end_timestamp",
                "status",
                "terminal_reason_code",
                "terminal_reason_text",
                "terminal_at",
            ]
        )
        self._broadcast_state_change(retryable=False)

    def end(self) -> None:
        self.mark_completed()
        self.generate_feedback()

    async def aend(self) -> None:
        await sync_to_async(self.end)()

    def generate_feedback(self) -> None:
        """Generate feedback for this simulation."""
        from .orca.services import GenerateInitialFeedback

        GenerateInitialFeedback.task.using(context={"simulation_id": self.pk}).enqueue()

    def calculate_metadata_checksum(self) -> str:
        from hashlib import sha256

        # Order by Metadata type (formerly known as attribute), then
        # Order by key for stable checksum
        entries = (
            self.metadata.select_related("polymorphic_ctype")
            .order_by("polymorphic_ctype__model", "key", "value")
            .values_list("polymorphic_ctype__model", "key", "value")
        )
        data = "|".join(
            f"{polymorphic_ctype__model}:{key}:{value}"
            for polymorphic_ctype__model, key, value in entries
        )
        return sha256(data.encode("utf-8")).hexdigest()

    @property
    def formatted_patient_history(self) -> list[dict]:
        """Return all Patient History metadata as a list of dicts for this Simulation."""
        qs = self.metadata.instance_of(PatientHistory)
        return [hx.to_dict() for hx in qs]

    @classmethod
    def build(cls, **kwargs):
        """Class method factory for creating simulations"""
        try:
            asyncio.get_running_loop()
            raise RuntimeError("Simulation.build() called in async context; use abuild()")
        except RuntimeError:
            return async_to_sync(cls.abuild)(**kwargs)

    @classmethod
    async def abuild(
        cls, *, user=None, prompt: Prompt = None, app_name=None, from_scenario=False, **kwargs
    ):
        """Class method factory for creating simulations"""

        if not user and not from_scenario:
            raise ValueError("Simulation must have a user")

        if from_scenario:
            # TODO: add `Simulation.abuild(from_scenario=True) feature
            logger.error(
                "Simulation.abuild() called with `from_scenario=True`, but feature is not implemented yet."
            )

        logger.info(f"starting Simulation build for {app_name} (user={user})")
        logger.debug(
            "... abuild(%s, %s, %s, %s, %s)", user, prompt, app_name, from_scenario, kwargs
        )

        # Collect valid concrete field names to avoid passing stray kwargs to .acreate()
        model_field_names = {
            f.name
            for f in cls._meta.get_fields()
            if getattr(f, "concrete", False) and not getattr(f, "auto_created", False)
        }

        # Normalize user to instance
        if isinstance(user, (str, int)):
            try:
                pk = int(user)
            except (TypeError, ValueError) as err:
                raise ValueError(
                    "`user` must be a User instance or an integer primary key"
                ) from err
            User = get_user_model()  # noqa: 8106
            user = await User.objects.select_related("role").aget(pk=pk)

        create_kwargs = {k: v for k, v in kwargs.items() if k in model_field_names}
        instance = await cls.objects.acreate(
            user=user,
            **create_kwargs,
        )

        return instance

    @classmethod
    def resolve(cls, _simulation: "Simulation | int") -> "Simulation":
        """
        Accept either a Simulation instance or its primary-key integer
        and return the corresponding Simulation instance.

        :param _simulation: Simulation instance or primary-key integer
        :type _simulation: Simulation | int
        :return: Simulation instance
        """
        if isinstance(_simulation, cls):
            return _simulation
        try:
            return cls.objects.get(pk=_simulation)
        except (TypeError, ValueError, ObjectDoesNotExist) as err:
            raise ValueError(f"Cannot resolve {cls.__name__} with input {_simulation!r}") from err

    @classmethod
    async def aresolve(cls, _simulation: "Simulation | int") -> "Simulation":
        """
        Async accept either a Simulation instance or its primary-key integer
        and return the corresponding Simulation instance.

        :param _simulation: Simulation instance or primary-key integer
        :type _simulation: Simulation | int

        :return: Simulation instance
        :rtype: Simulation

        :raises ValueError: If the provided value is not a Simulation instance or an integer.
        """
        if isinstance(_simulation, cls):
            return _simulation
        try:
            return await cls.objects.aget(pk=_simulation)
        except (TypeError, ValueError, ObjectDoesNotExist) as err:
            raise ValueError(f"Cannot resolve {cls.__name__} with input {_simulation!r}") from err

    def save(self, *args, **kwargs):
        # Handle display name update if the full name is changed
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


class SimulationMetadata(PersistModel, PolymorphicModel):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name="metadata")

    key = models.CharField(max_length=255)
    value = models.TextField()

    service_call_attempt = models.ForeignKey(
        "orchestrai_django.ServiceCallAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="simulation_metadata",
        help_text="Link to service call attempt that produced this metadata",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["simulation", "key"],
                name="uniq_simulation_key",
            )
        ]

    @classmethod
    def format_patient_history(cls, history_metadata: QuerySet) -> list[dict]:
        warnings.warn(
            "`cls.format_patient_history` is deprecated. Use 'PatientHistory.to_dict()' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from collections import defaultdict

        grouped = defaultdict(dict)
        for entry in history_metadata:
            key = entry.key
            value = entry.value
            prefix, field = key.rsplit(" ", 1)
            grouped[prefix][field] = value
        logger.debug(f"grouped: {grouped}")

        formatted = [
            {
                "key": prefix,
                "value": "{diagnosis} ({is_resolved}, {duration})".format(
                    diagnosis=data.get("diagnosis", "Unknown").title(),
                    is_resolved=data.get("is_resolved", "Unknown"),
                    duration=data.get("duration", "Unknown"),
                ),
            }
            for prefix, data in grouped.items()
        ]
        logger.debug(f"formatted: {formatted}")

        return formatted

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        self.simulation.metadata_checksum = self.simulation.calculate_metadata_checksum()
        self.simulation.save(update_fields=["metadata_checksum"])


class LabResult(SimulationMetadata):
    """Store a lab result for the specified simulation."""

    panel_name = models.CharField(max_length=100, null=True, blank=True)
    result_unit = models.CharField(max_length=20, blank=True, null=True)
    reference_range_low = models.CharField(max_length=50, blank=True, null=True)
    reference_range_high = models.CharField(max_length=50, blank=True, null=True)
    result_flag = models.CharField(max_length=20)  # Normal, Abnormal
    result_comment = models.TextField(blank=True, null=True)

    @property
    def result_name(self) -> str:
        return self.key

    @property
    def result(self) -> str:
        return self.value

    @property
    def attribute(self) -> str:
        return self.__class__.__name__

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "result_name": self.key,
            "panel_name": self.panel_name or None,
            "value": self.value,
            "unit": self.result_unit,
            "reference_range_high": self.reference_range_high,
            "reference_range_low": self.reference_range_low,
            "flag": self.result_flag,
            "attribute": self.attribute,
            "type": self.attribute,
        }

    def __str__(self) -> str:
        return f"Sim#{self.simulation.pk} {self.__class__.__name__} Metafield (id:{self.pk}): {self.key}"


class RadResult(SimulationMetadata):
    """Store a rad result for the specified simulation."""

    result_flag = models.CharField(max_length=10)

    @property
    def result_name(self) -> str:
        return self.key

    @property
    def result(self) -> str:
        return self.value

    @property
    def attribute(self) -> str:
        return self.__class__.__name__

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "result_name": self.key,
            "result": self.value,
            "result_flag": self.result_flag,
            "attribute": self.attribute,
            "type": self.attribute,
        }

    def __str__(self) -> str:
        return f"Sim#{self.simulation.pk} {self.__class__.__name__} Metafield (id:{self.pk}): {self.key}"


class PatientDemographics(SimulationMetadata):
    """Store patient demographics for the specified simulation."""

    @property
    def attribute(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        return f"Sim#{self.simulation.pk} {self.__class__.__name__} Metafield (id:{self.pk}): {self.key}"


class PatientHistory(SimulationMetadata):
    """Store patient demographics for the specified simulation."""

    is_resolved = models.BooleanField(default=False)
    duration = models.CharField(max_length=100)

    @property
    def diagnosis(self) -> str:
        return self.key

    def to_dict(self):
        return {
            "diagnosis": self.diagnosis,
            "is_resolved": self.is_resolved,
            "duration": self.duration,
            "value": self.value,
            "summary": f"History of {self.diagnosis} ({'now resolved' if self.is_resolved else 'ongoing'}, for {self.duration})",
        }

    @property
    def attribute(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        return f"Sim#{self.simulation.pk} {self.__class__.__name__} Metafield (id:{self.pk}): {self.key}"


class SimulationFeedback(SimulationMetadata):
    @property
    def attribute(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        return f"Sim#{self.simulation.pk} {self.__class__.__name__} Metafield (id:{self.pk}): {self.key}"


class SimulationImage(models.Model):
    """Store image for the specified simulation."""

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    modified_at = models.DateTimeField(auto_now=True, editable=False)

    mime_type = models.CharField(max_length=100, blank=True, null=True)

    simulation = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name="images")

    provider_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="OpenAI image ID (if applicable)",
    )

    def openai_id(self) -> str:
        """Return the OpenAI image ID, if available.

        For backwards compatibility, this method is deprecated and will be removed in the future.
        """
        logger.warning(
            "`openai_id` is deprecated. Use `provider_id` instead.", PendingDeprecationWarning
        )
        return self.provider_id

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=True,
        help_text="Unique identifier for this image",
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

    def save(self, *args, **kwargs):
        # Guess MIME type from file name (fallback approach)
        guessed_mime, _ = mimetypes.guess_type(self.original.name)

        if guessed_mime:
            if self.mime_type:
                if self.mime_type != guessed_mime:
                    logger.warning(
                        f"Mismatch in MIME type for {self.original.name}: "
                        f"declared={self.mime_type}, guessed={guessed_mime}"
                    )
                    raise ValidationError(f"MIME type mismatch: {self.mime_type} != {guessed_mime}")
            else:
                self.mime_type = guessed_mime
        else:
            logger.warning(f"Could not guess MIME type for {self.original.name}")
            self.mime_type = "application/octet-stream"

        super().save(*args, **kwargs)
