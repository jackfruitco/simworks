import logging

from core.utils.hash import compute_fingerprint
from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from .querysets.response_queryset import ResponseQuerySet

logger = logging.getLogger(__name__)


class ResponseType(models.TextChoices):
    INITIAL = ("I", _("initial"))
    REPLY = ("R", _("reply"))
    FEEDBACK = ("F", _("feedback"))
    MEDIA = ("M", _("media"))
    PATIENT_RESULTS = ("TR", _("patient results"))


class Response(models.Model):
    """Object to store data for the OpenAI responses."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    objects = ResponseQuerySet.as_manager()

    simulation = models.ForeignKey(
        "simcore.Simulation", related_name="responses_v1", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="responses_v1", on_delete=models.CASCADE
    )

    raw = models.JSONField(verbose_name="OpenAI Raw Response")
    id = models.CharField("OpenAI Response ID", max_length=255, primary_key=True)
    order = models.PositiveIntegerField(editable=False)
    type = models.CharField(
        choices=ResponseType, default=ResponseType.REPLY, max_length=2
    )

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
