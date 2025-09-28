# simcore/models.py
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import uuid
import warnings
from datetime import timedelta

from asgiref.sync import sync_to_async, async_to_sync
from autoslug import AutoSlugField
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import models
from django.db.models import QuerySet
from django.utils.timezone import now
from imagekit.models import ImageSpecField
from pilkit.processors import Thumbnail
from polymorphic.models import PolymorphicModel

from simcore.ai.promptkit import Prompt as PromptDTO
from simcore.ai.prompts.sections.modifiers import UserRoleSection, UserHistorySection
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
        related_name="%(app_label)s_session",
        related_query_name="%(app_label)s_session",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        abstract = True


class Simulation(models.Model):
    # objects = SimulationManager()

    start_timestamp = models.DateTimeField(auto_now_add=True)
    end_timestamp = models.DateTimeField(blank=True, null=True)

    time_limit = models.DurationField(
        blank=True, null=True, help_text="Optional max duration for this simulation"
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    openai_model = models.CharField(blank=True, null=True, max_length=128)
    metadata_checksum = models.CharField(max_length=64, blank=True, null=True)

    # `prompt` is used for backwards compatibility with older simulations
    # that used prompt_v1 or prompt_v2 (simai.promptkit)
    prompt = models.JSONField(
        help_text="The prompt to use as AI instructions",
    )

    # used for new simulations that use prompt_v3 (simcore.ai.promptkit)
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

    async def aget_previous_response(self) -> AIResponse | None:
        """Return most recent AIResponse for this simulation, or None."""
        return await self.responses.order_by("-created_at").afirst()

    def get_previous_response(self) -> AIResponse | None:
        """Return most recent AIResponse for this simulation, or None."""
        return self.responses.order_by("-created_at").first()

    def get_previous_response_id(self) -> str | None:
        r = self.get_previous_response()
        return r.provider_id or None if r else None

    async def aget_previous_response_id(self) -> str | None:
        r = await self.aget_previous_response()
        return r.provider_id or None if r else None

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

    async def aend(self):
        await sync_to_async(self.end)()

    def generate_feedback(self):
        from simai.tasks import generate_feedback as generate_feedback_task

        func_name = "generate_feedback"

        try:
            generate_feedback_task.delay(__simulation_id=self.pk)
        except Exception as e:
            logger.warning(f"[{func_name}] Celery task failed to enqueue: {e}")

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
    def formatted_patient_history(self):
        raw = self.metadata.filter(attribute="patient history")
        return SimulationMetadata.format_patient_history(raw)

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
            cls,
            *,
            user=None,
            prompt: PromptDTO = None,
            lab=None,
            is_template=False,
            use_prompt_v2=False,
            **kwargs
    ):
        """Class method factory for creating simulations"""
        if not user and not is_template:
            raise ValueError("Simulation must have a user unless marked as template.")

        logger.info(f"starting Simulation build for {lab} (user={user})")
        logger.debug("... abuild(%s, %s, %s, %s, %s)", user, prompt, lab, is_template, kwargs)

        lab = str(lab).lower().strip() if lab else None

        # Collect valid concrete field names to avoid passing stray kwargs to .acreate()
        model_field_names = {f.name for f in cls._meta.get_fields() if
                             getattr(f, "concrete", False) and not getattr(f, "auto_created", False)}

        # Normalize user to instance
        if isinstance(user, (str, int)):
            try:
                pk = int(user)
            except (TypeError, ValueError):
                raise ValueError("`user` must be a User instance or an integer primary key")
            User = get_user_model()
            user = await User.objects.select_related("role").aget(pk=pk)

        # ---- Legacy (prompt_v2) path -------------------------------------------------
        if use_prompt_v2:
            import warnings
            warnings.warn("Using deprecated prompt_v2 (simai.promptkit)", DeprecationWarning)
            if not prompt and user and lab:
                from simai.prompts import Prompt as LegacyPrompt  # legacy builder

                prompt_kwargs = {
                    "user": user,
                    "role": getattr(user, "role", None),
                    "lab": lab,
                    "modifiers": kwargs.pop("modifiers", []),
                    "include_default": kwargs.pop("include_default", False),
                    "include_history": kwargs.pop("include_history", False),
                }
                prompt = await LegacyPrompt.abuild(**prompt_kwargs)

                # Prevent the save() hook from generating another legacy prompt
                create_kwargs = {k: v for k, v in kwargs.items() if k in model_field_names}
                return await cls.objects.acreate(
                    user=user,
                    prompt=prompt,
                    prompt_meta={"version": 2},
                    **create_kwargs,
                )

        # ---- New engine (prompt_v3) path --------------------------------------------
        logger.debug(f"... using PromptEngine (v3)")
        p: PromptDTO
        if not prompt and lab:
            from simcore.ai.promptkit import PromptEngine
            from simcore.ai.prompts.sections.modifiers import (
                PatientNameSection,
                UserRoleSection,
                UserHistorySection
            )

            try:
                from simcore.ai.utils.imports import resolve_initial_section
                init_cls = resolve_initial_section(lab)
            except Exception as e:
                raise ValueError(
                    f"Unable to resolve initial prompt section for lab={lab!r}"
                ) from e

            # Pass context so sections can render
            prompt_context = {
                "user": user,
                "role": getattr(user, "role", None),
                "lab": lab,
            }

            logger.debug(f"...... starting PromptEngine\n(engine context:\t{prompt_context})")
            ctx = {**prompt_context, **kwargs}
            p = await PromptEngine.abuild_from(
                init_cls,
                PatientNameSection,
                UserRoleSection,
                UserHistorySection,
                **ctx)

        else:
            # Coerce/validate provided prompt
            if isinstance(prompt, dict):
                p = PromptDTO(
                    instruction=(prompt.get("instruction") or ""),
                    message=prompt.get("message"),
                    meta=prompt.get("meta") or {},
                )
            else:
                # Expect a Prompt-like object with `.instruction` and `.message`
                if not hasattr(prompt, "instruction"):
                    raise ValueError(
                        "Provided prompt must have an 'instruction' attribute or be a dict with 'instruction'.")
                p = prompt

        if not p:
            raise ValueError("Prompt or Lab must be provided to build a Simulation.")

        if not p.instruction:
            raise ValueError("Prompt instruction must be provided to build a Simulation.")

        # Enrich prompt metadata
        p.meta.update({
            "lab": lab,
            # "sections": [...],        # TODO add when the engine exposes used labels
        })

        logger.debug(f"...... PromptEngine complete: {print(p)}")

        logger.debug(f"... creating Simulation")
        create_kwargs = {k: v for k, v in kwargs.items() if k in model_field_names}
        return await cls.objects.acreate(
            user=user,
            prompt=p.to_dict(),  # TODO prompt_json is deprecated, remove in future
            prompt_instruction=p.instruction,
            prompt_message=p.message or "",
            prompt_meta=p.meta,
            **create_kwargs,
        )

    @classmethod
    def resolve(cls, _simulation: "Simulation | int") -> "Simulation":
        """
        Accept either a Simulation instance or its primary-key integer,
        and return the corresponding Simulation instance.

        :param _simulation: Simulation instance or primary-key integer
        :type _simulation: Simulation | int
        :return: Simulation instance
        """
        if isinstance(_simulation, cls):
            return _simulation
        try:
            return cls.objects.get(pk=_simulation)
        except (TypeError, ValueError, ObjectDoesNotExist):
            raise ValueError(f"Cannot resolve {cls.__name__} with input {_simulation!r}")

    @classmethod
    async def aresolve(cls, _simulation: "Simulation | int") -> "Simulation":
        """
        Async accept either a Simulation instance or its primary-key integer,
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
        except (TypeError, ValueError, ObjectDoesNotExist):
            raise ValueError(f"Cannot resolve {cls.__name__} with input {_simulation!r}")

    def save(self, *args, **kwargs):
        from simai.prompts import build_prompt

        # Ensure the prompt is set based on user.role if not already provided
        if not self.prompt:
            if not self.user:
                raise ValueError("Cannot assign default prompt without a user.")
            # self.prompt = get_or_create_prompt(app_label="chatlab", user=self.user, role=getattr(self.user, "role", None))
            # self.prompt = build_prompt(lab="chatlab", user=self.user, role=getattr(self.user, "role", None))
            self.prompt = build_prompt(lab="chatlab", user=self.user)

        # Handle display name update if the full name is changed
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

    def __str__(self) -> str:
        base = f"Simulation {self.pk}"
        if self.diagnosis:
            base = base + f": {self.chief_complaint}"
        return base


class SimulationMetadata(PolymorphicModel):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="metadata"
    )

    key = models.CharField(max_length=255)
    value = models.TextField()

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
        is_new = self.pk is None
        super().save(*args, **kwargs)

        self.simulation.metadata_checksum = (
            self.simulation.calculate_metadata_checksum()
        )
        self.simulation.save(update_fields=["metadata_checksum"])


class LabResult(SimulationMetadata):
    """Store a lab result for the specified simulation."""

    panel_name = models.CharField(max_length=100, null=True, blank=True)
    result_unit = models.CharField(max_length=20)
    reference_range_low = models.CharField(max_length=20)
    reference_range_high = models.CharField(max_length=20)
    result_flag = models.CharField(max_length=20)
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
            "summary": f"History of {self.diagnosis} ({"now resolved" if self.is_resolved else "ongoing"}, for {self.duration})",
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

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="images"
    )

    provider_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="OpenAI image ID (if applicable)",
    )

    def openai_id(self) -> str:
        """Return the OpenAI image ID, if available.

        For backwards compatibility, this method is deprecated and will be removed in future.
        """
        logger.warning(
            "`openai_id` is deprecated. Use `provider_id` instead.",
            PendingDeprecationWarning
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
                    raise ValidationError(
                        f"MIME type mismatch: {self.mime_type} != {guessed_mime}"
                    )
            else:
                self.mime_type = guessed_mime
        else:
            logger.warning(f"Could not guess MIME type for {self.original.name}")
            self.mime_type = "application/octet-stream"

        super().save(*args, **kwargs)


class AIResponse(models.Model):
    """Store AI response for the specified simulation."""

    created_at = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True, editable=False)

    simulation = models.ForeignKey(
        Simulation, on_delete=models.CASCADE, related_name="responses"
    )

    provider_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    provider = models.CharField(default="openai", max_length=255)
    raw = models.JSONField(verbose_name="raw AI response", blank=True, null=True)
    normalized = models.JSONField(verbose_name="normalized AI response")

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["simulation", "created_at"]
        indexes = [
            models.Index(fields=["simulation", "-created_at"], name="airesp_sim_createdat_desc"),
            models.Index(fields=["simulation", "provider_id"], name="airesp_sim_providerid_idx"),
        ]

    def __str__(self):
        return f"AI Response id {self.pk} (Simulation id {self.simulation.pk}; created_at={self.created_at})"
