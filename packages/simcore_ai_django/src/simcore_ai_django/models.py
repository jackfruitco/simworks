
# simcore_ai_django/models.py
from __future__ import annotations

from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """Abstract base with created/updated timestamps (UTC)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AIRequestAudit(TimestampedModel):
    """Audit row for an outbound AI request.

    Stores the normalized request payload (messages/tools/response_format) and routing metadata.
    This is append-only; do not update after creation except for bookkeeping fields.
    """

    # Correlation & identity
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    namespace = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    kind = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    service_name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    # Provider & client resolution
    provider_name = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    # Domain linkage (optional)
    simulation_pk = models.IntegerField(null=True, blank=True, db_index=True)

    # Transport/model flags
    model = models.CharField(max_length=128, null=True, blank=True)
    stream = models.BooleanField(default=False)

    # Normalized request payloads
    messages = models.JSONField(default=list)              # list[LLMRequestMessage]
    tools = models.JSONField(null=True, blank=True)        # list[BaseLLMTool] or equivalent

    # Response format (schema) fields
    response_format_cls = models.CharField(max_length=255, null=True, blank=True)
    response_format_adapted = models.JSONField(null=True, blank=True)
    response_format = models.JSONField(null=True, blank=True)

    # Prompt/render metadata (optional hints)
    prompt_meta = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "ai_request_audit"
        indexes = [
            models.Index(fields=["provider_name", "client_name"]),
            models.Index(fields=["namespace", "service_name"]),
            models.Index(fields=["correlation_id"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        ns = self.namespace or "?"
        return f"AIRequestAudit(id={self.pk}, ns={ns}, provider={self.provider_name}, model={self.model})"


class AIResponseAudit(TimestampedModel):
    """Audit row for an inbound AI response (success or failure)."""

    # Linkage back to request (if known)
    request = models.ForeignKey(
        AIRequestAudit, null=True, blank=True, on_delete=models.SET_NULL, related_name="responses"
    )

    # Correlation & identity
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    namespace = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    kind = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    service_name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    # Provider & client resolution
    provider_name = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    # Domain linkage (optional)
    simulation_pk = models.IntegerField(null=True, blank=True, db_index=True)

    # Timing
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Normalized response payload
    outputs = models.JSONField(default=list)          # list[LLMResponseItem]
    usage = models.JSONField(null=True, blank=True)   # LLMUsage
    provider_meta = models.JSONField(null=True, blank=True)

    # Error info (if any)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ai_response_audit"
        indexes = [
            models.Index(fields=["provider_name", "client_name"]),
            models.Index(fields=["namespace", "service_name"]),
            models.Index(fields=["correlation_id"]),
            models.Index(fields=["received_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        ns = self.namespace or "?"
        status = "ok" if not self.error else "error"
        return f"AIResponseAudit(id={self.pk}, ns={ns}, status={status})"


class AIOutbox(TimestampedModel):
    """Transactional outbox for AI-related domain events.

    Inline emit is the fast path; this table provides durability and retry.
    A periodic task can scan for undelivered rows and dispatch as fallback.
    """

    EVENT_CHOICES = [
        ("ai.request.sent", "AI request sent"),
        ("ai.response.received", "AI response received"),
        ("ai.response.ready", "AI response ready"),
    ]

    event_type = models.CharField(max_length=64, choices=EVENT_CHOICES, db_index=True)
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    namespace = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    provider_name = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    # Arbitrary payload (e.g., serialized DjangoLLMRequest/Response)
    payload = models.JSONField(default=dict)

    # Delivery bookkeeping
    dispatched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ai_outbox"
        indexes = [
            models.Index(fields=["event_type", "dispatched_at"]),
            models.Index(fields=["namespace", "correlation_id"]),
        ]

    def mark_dispatched(self) -> None:
        self.dispatched_at = timezone.now()
        self.save(update_fields=["dispatched_at", "updated_at"])

    def __str__(self) -> str:  # pragma: no cover
        return f"AIOutbox(id={self.pk}, event={self.event_type}, dispatched={bool(self.dispatched_at)})"
