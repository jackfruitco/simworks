# orchestrai_django/models.py
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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


class AIRequestAudit(TimestampedModel):
    """Audit record for outbound AI/LLM requests.

    Stores the full OrchestrAI Request JSON along with extracted fields
    for querying. Replaces AIOutbox for request tracking.

    Lifecycle:
        1. Created in tasks.run_service_call() after request is built
        2. AIResponseAudit linked after response received
        3. Domain objects link back via ai_response_audit FK
    """

    # Identity fields
    correlation_id = models.UUIDField(db_index=True)
    service_identity = models.CharField(max_length=255, db_index=True)
    namespace = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    kind = models.CharField(max_length=128, null=True, blank=True)
    name = models.CharField(max_length=128, null=True, blank=True)

    # Provider info
    provider_name = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=128, null=True, blank=True)
    model = models.CharField(max_length=128, null=True, blank=True)

    # Full OrchestrAI Request JSON
    raw = models.JSONField(help_text="Request.model_dump(mode='json')")

    # Extracted fields for querying
    messages = models.JSONField(default=list, help_text="Extracted input messages")
    tools = models.JSONField(null=True, blank=True)
    response_schema_identity = models.CharField(max_length=255, null=True, blank=True)

    # Object linkage
    object_db_pk = models.IntegerField(null=True, blank=True, db_index=True)
    service_call = models.ForeignKey(
        "ServiceCallRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_requests",
    )

    # Event tracking (migrated from AIOutbox)
    dispatched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ai_request_audit"
        indexes = [
            models.Index(fields=["correlation_id"]),
            models.Index(fields=["service_identity"]),
            models.Index(fields=["namespace", "kind", "name"]),
            models.Index(fields=["provider_name", "model"]),
            models.Index(fields=["dispatched_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"AIRequestAudit(id={self.pk}, service={self.service_identity}, correlation={self.correlation_id})"

    # ---- identity conveniences (read-side) ---------------------------------
    @property
    def identity(self) -> Identity:
        return Identity(
            domain="requests",
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
    """Audit record for inbound AI/LLM responses.

    Stores both the full OrchestrAI Response JSON and the raw provider response
    (before normalization) for complete audit trail.

    Lifecycle:
        1. Created in tasks.run_service_call() after response received
        2. Links to corresponding AIRequestAudit
        3. Domain objects (Message, SimulationMetadata) link via ai_response_audit FK

    Key Fields:
        - raw: Full OrchestrAI Response JSON (normalized)
        - provider_raw: Raw provider response before OrchestrAI normalization
    """

    # Links
    ai_request = models.ForeignKey(
        "AIRequestAudit",
        on_delete=models.CASCADE,
        related_name="responses",
    )
    service_call = models.ForeignKey(
        "ServiceCallRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_responses",
    )

    # Correlation
    correlation_id = models.UUIDField(db_index=True)
    request_correlation_id = models.UUIDField(null=True, blank=True, db_index=True)

    # Full Response JSON
    raw = models.JSONField(help_text="Response.model_dump(mode='json')")

    # Raw provider response (before OrchestrAI normalization)
    provider_raw = models.JSONField(
        null=True,
        blank=True,
        help_text="provider_meta['raw'] - untouched provider response",
    )

    # Extracted fields for querying
    provider_name = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=128, null=True, blank=True)
    model = models.CharField(max_length=128, null=True, blank=True)
    finish_reason = models.CharField(max_length=64, null=True, blank=True)
    provider_response_id = models.CharField(max_length=255, null=True, blank=True)

    # Usage tracking
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)

    # Structured output
    structured_data = models.JSONField(null=True, blank=True)
    execution_metadata = models.JSONField(default=dict)

    # Timing
    received_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "ai_response_audit"
        indexes = [
            models.Index(fields=["correlation_id"]),
            models.Index(fields=["request_correlation_id"]),
            models.Index(fields=["provider_name", "model"]),
            models.Index(fields=["received_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"AIResponseAudit(id={self.pk}, correlation={self.correlation_id}, tokens={self.total_tokens})"


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

    # Domain persistence tracking (for two-phase commit pattern)
    domain_persisted = models.BooleanField(default=False)
    domain_persist_error = models.TextField(null=True, blank=True)
    domain_persist_attempts = models.IntegerField(default=0)

    class Meta:
        db_table = "service_call_record"
        indexes = [
            models.Index(fields=["service_identity", "backend"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["status", "domain_persisted", "finished_at"]),
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


class PersistedChunk(TimestampedModel):
    """Tracks which structured outputs have been persisted to domain models.

    Provides idempotency for the persistence drain worker - ensures each
    schema output is persisted exactly once even with retries.

    Key Concept:
        A "chunk" is a structured output (validated by a schema) from a service
        response that needs to be persisted to domain models. This table tracks
        which chunks have been successfully persisted.

    Idempotency:
        Unique constraint on (call_id, schema_identity) ensures each chunk
        is persisted exactly once. Handlers use get_or_create pattern.

    Example:
        Service returns PatientInitialOutputSchema → creates Message + Metadata
        PersistedChunk records: call_id="abc123", schema_identity="schemas.chatlab...",
                                domain_object points to Message instance
    """

    # Service call that produced this chunk
    call_id = models.CharField(max_length=64, db_index=True)

    # Schema that structured this output
    schema_identity = models.CharField(max_length=255, db_index=True)

    # Originating namespace (Django app that owns the handler)
    namespace = models.CharField(max_length=255, db_index=True)

    # Handler that persisted this chunk
    handler_identity = models.CharField(max_length=255)

    # Primary domain object created (polymorphic reference)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    domain_object = GenericForeignKey("content_type", "object_id")

    # Tracking metadata
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "persisted_chunk"
        unique_together = [("call_id", "schema_identity")]
        indexes = [
            models.Index(fields=["call_id", "schema_identity"]),
            models.Index(fields=["namespace", "schema_identity"]),
            models.Index(fields=["persisted_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"PersistedChunk(call={self.call_id}, schema={self.schema_identity})"
