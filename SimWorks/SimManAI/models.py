from django.db import models
from django.conf import settings
from SimManAI.querysets.response_queryset import ResponseQuerySet

class Response(models.Model):
    simulation = models.ForeignKey("ChatLab.Simulation", related_name="responses", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="responses", on_delete=models.CASCADE)
    raw = models.TextField(verbose_name="OpenAI Raw Response")
    message = models.ForeignKey("ChatLab.Message", null=True, blank=True, related_name="response", on_delete=models.SET_NULL)
    id = models.CharField("OpenAI Response ID", max_length=255, primary_key=True)

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)

    created = models.DateTimeField(auto_now_add=True)

    objects = ResponseQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["created"]),
        ]

    def __str__(self):
        return f"Response [{self.input_tokens}+{self.output_tokens} tokens] for Sim #{self.simulation.id}"

    def tally(self):
        return self.input_tokens + self.output_tokens + self.reasoning_tokens