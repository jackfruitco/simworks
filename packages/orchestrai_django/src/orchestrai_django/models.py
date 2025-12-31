# orchestrai_django/models.py
from django.db import models
from django.utils import timezone
from orchestrai.components.services.calls import ServiceCall, assert_jsonable
from orchestrai.identity import Identity


class TimestampedModel(models.Model):
    """Abstract base with created/updated timestamps (UTC)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Identity fields now use the centralized tuple4 (domain, namespace, group, name).
# The 'service_name' field has been migrated to 'name' for consistency.
class AIRequestAudit(TimestampedModel):
    """Audit row for an outbound AI request.

    Stores the normalized request payload (input/tools/response_schema_json) and routing metadata.
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
    messages = models.JSONField(default=list)              # list[InputItem]
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
        domain = getattr(self, "domain", None) or "default"
        return Identity(
            domain=domain,
            namespace=self.namespace or "default",
            group=self.kind or "default",
            name=self.name or "default",
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str, str]:
        return self.identity.as_tuple

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
    outputs = models.JSONField(default=list)          # list[OutputItem]
    usage = models.JSONField(null=True, blank=True)   # UsageContent
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
        domain = getattr(self, "domain", None) or "default"
        return Identity(
            domain=domain,
            namespace=self.namespace or "default",
            group=self.kind or "default",
            name=self.name or "default",
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str, str]:
        return self.identity.as_tuple

    @property
    def identity_str(self) -> str:
        return self.identity.as_str


class AIOutbox(TimestampedModel):
    """Transactional outbox for AI-related domain events.

    Inline emit is the fast path; this table provides durability and retry.
    A periodic task can scan for undelivered rows and dispatch as fallback.
    """

    EVENT_CHOICES = [
        ("orchestrai.request.sent", "AI request sent"),
        ("orchestrai.response.received", "AI response received"),
        ("orchestrai.response.ready", "AI response ready"),
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
        domain = getattr(self, "domain", None) or "default"
        return Identity(
            domain=domain,
            namespace=self.namespace or "default",
            group=self.kind or "default",
            name=self.name or "default",
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str, str]:
        return self.identity.as_tuple

    @property
    def identity_str(self) -> str:
        return self.identity.as_str


class ServiceCallRecord(TimestampedModel):
    """Persistent record of a service call dispatched from Django."""

    id = models.CharField(primary_key=True, max_length=64)
    service_identity = models.CharField(max_length=255, db_index=True)
    service_kwargs = models.JSONField(default=dict)
    status = models.CharField(max_length=32)
    input = models.JSONField(default=dict)
    context = models.JSONField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    dispatch = models.JSONField(default=dict)
    backend = models.CharField(max_length=64, default="immediate")
    queue = models.CharField(max_length=128, null=True, blank=True)
    task_id = models.CharField(max_length=128, null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "service_call_record"
        indexes = [
            models.Index(fields=["service_identity", "backend"]),
            models.Index(fields=["queue"]),
        ]

    def _coerce_datetime(self, value):
        if value is None:
            return None
        if timezone.is_aware(value):
            return value
        try:
            return timezone.make_aware(value)
        except Exception:
            return value

    def update_from_call(self, call: ServiceCall) -> None:
        """Synchronize stored fields from a :class:`ServiceCall`."""

        dispatch = dict(call.dispatch or {})
        backend = dispatch.get("backend") or self.backend
        queue = dispatch.get("queue") or self.queue
        task_id = dispatch.get("task_id") or self.task_id

        self.status = call.status
        self.input = call.input
        self.context = call.context
        self.result = call.result
        self.error = call.error
        self.dispatch = dispatch
        self.backend = backend
        self.queue = queue
        self.task_id = task_id

        self.created_at = self._coerce_datetime(call.created_at)
        self.started_at = self._coerce_datetime(call.started_at)
        self.finished_at = self._coerce_datetime(call.finished_at)

    def as_call(self) -> ServiceCall:
        """Rehydrate a :class:`ServiceCall` from the persisted payload."""

        dispatch = dict(self.dispatch or {})
        dispatch.setdefault("backend", self.backend)
        if self.queue:
            dispatch.setdefault("queue", self.queue)
        if self.task_id:
            dispatch.setdefault("task_id", self.task_id)

        call = ServiceCall(
            id=self.id,
            status=self.status,
            input=self.input,
            context=self.context,
            result=self.result,
            error=self.error,
            dispatch=dispatch,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )
        return call

    def to_jsonable(self) -> dict:
        payload = self.as_call().to_jsonable()
        payload["service_identity"] = self.service_identity
        payload["service_kwargs"] = self.service_kwargs
        assert_jsonable(payload)
        return payload

    def __str__(self) -> str:  # pragma: no cover
        return f"ServiceCallRecord(id={self.pk}, service={self.service_identity}, status={self.status})"
