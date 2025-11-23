# simcore_ai_django/models.py


from django.db import models
from django.utils import timezone
from simcore_ai.identity import Identity


class TimestampedModel(models.Model):
    """Abstract base with created/updated timestamps (UTC)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Identity fields now use the centralized tuple3 (namespace, kind, name).
# The 'service_name' field has been migrated to 'name' for consistency.
class AIRequestAudit(TimestampedModel):
    """Audit row for an outbound AI request.

    Stores the normalized request payload (messages/tools/output_schema) and routing metadata.
    This is append-only; do not update after creation except for bookkeeping fields.
    """

    # Correlation & identity
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    namespace = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    kind = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

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
            models.Index(fields=["namespace", "name"]),
            models.Index(fields=["correlation_id"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        ns = self.namespace or "?"
        return f"AIRequestAudit(id={self.pk}, ns={ns}, name={self.name or '?'}, provider={self.provider_name}, model={self.model})"

    # ---- identity conveniences (read-side) ---------------------------------
    @property
    def identity(self) -> Identity:
        return Identity(
            namespace=self.namespace or "default",
            kind=self.kind or "default",
            name=self.name or "default",
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str]:
        return self.identity.as_tuple3

    @property
    def identity_str(self) -> str:
        return self.identity.as_str


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
    name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

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
            models.Index(fields=["namespace", "name"]),
            models.Index(fields=["correlation_id"]),
            models.Index(fields=["received_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        ns = self.namespace or "?"
        status = "ok" if not self.error else "error"
        return f"AIResponseAudit(id={self.pk}, ns={ns}, name={self.name or '?'}, status={status})"

    # ---- identity conveniences (read-side) ---------------------------------
    @property
    def identity(self) -> Identity:
        return Identity(
            namespace=self.namespace or "default",
            kind=self.kind or "default",
            name=self.name or "default",
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str]:
        return self.identity.as_tuple3

    @property
    def identity_str(self) -> str:
        return self.identity.as_str


class AIOutbox(TimestampedModel):
    """Transactional outbox for AI-related domain events.

    Inline emit is the fast path; this table provides durability and retry.
    A periodic task can scan for undelivered rows and dispatch as fallback.
    """

    EVENT_CHOICES = [
        ("simcore.request.sent", "AI request sent"),
        ("simcore.response.received", "AI response received"),
        ("simcore.response.ready", "AI response ready"),
    ]

    event_type = models.CharField(max_length=64, choices=EVENT_CHOICES, db_index=True)
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    namespace = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    kind = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    provider_name = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    # Arbitrary payload (e.g., serialized DjangoRequest/Response)
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
            models.Index(fields=["namespace", "kind", "name"]),
            models.Index(fields=["namespace", "correlation_id"]),
        ]

    # ---- identity conveniences (read-side) ---------------------------------
    @property
    def identity(self) -> Identity:
        return Identity(
            namespace=self.namespace or "default",
            kind=self.kind or "default",
            name=self.name or "default",
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str]:
        return self.identity.as_tuple3

    @property
    def identity_str(self) -> str:
        return self.identity.as_str

    def mark_dispatched(self) -> None:
        self.dispatched_at = timezone.now()
        self.save(update_fields=["dispatched_at", "updated_at"])

    def __str__(self) -> str:  # pragma: no cover
        return f"AIOutbox(id={self.pk}, event={self.event_type}, ident={self.identity.as_str}, dispatched={bool(self.dispatched_at)})"
