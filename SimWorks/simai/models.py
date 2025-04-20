from django.db import models
from django.conf import settings
from django.utils.timezone import now

from core.utils import compute_fingerprint
from .querysets.response_queryset import ResponseQuerySet

from django.utils.translation import gettext_lazy as _


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
    fingerprint = models.CharField(
        max_length=64,
        editable=False,
        db_index=True,
        unique=True
    )
    is_archived = models.BooleanField(default=False)

    title = models.CharField(max_length=255, unique=True)
    text = models.TextField(help_text="The scenario prompt sent to OpenAI.")
    summary = models.TextField(help_text="The prompt summary.")

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

    # in Prompt model
    def compute_own_fingerprint(self):
        return compute_fingerprint(self.title, self.text)


class ResponseType(models.TextChoices):
    INITIAL = ("I", _("initial"))
    REPLY = ("R", _("reply"))
    FEEDBACK = ("F", _("feedback"))


class Response(models.Model):
    """Object to store data for the OpenAI responses."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    objects = ResponseQuerySet.as_manager()

    simulation = models.ForeignKey("chatlab.Simulation", related_name="responses", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="responses", on_delete=models.CASCADE)
    raw = models.TextField(verbose_name="OpenAI Raw Response")
    id = models.CharField("OpenAI Response ID", max_length=255, primary_key=True)
    order = models.PositiveIntegerField(editable=False)
    type = models.CharField(choices=ResponseType, default=ResponseType.REPLY, max_length=2)


    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)


    class Meta:
        ordering = ("simulation", "order")
        unique_together = ("simulation", "order")
        indexes = [
            models.Index(fields=["created"]),
        ]

    def __str__(self):
        return f"Sim#{self.simulation.id} Response #{self.order} [{self.input_tokens}+{self.output_tokens} tokens]"

    def tally(self):
        return self.input_tokens + self.output_tokens + self.reasoning_tokens

    def save(self, *args, **kwargs):
        if self.order is None:
            max_order = Response.objects.filter(simulation=self.simulation).aggregate(
                models.Max("order")
            )["order__max"]
            self.order = (max_order or 0) + 1
        super().save(*args, **kwargs)