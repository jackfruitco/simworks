# orchestrai_django/models.py
from uuid import uuid4

from django.db import models
from django.db.models import Max
from django.utils import timezone
from orchestrai.components.services.calls import ServiceCall as ServiceCallDataclass, assert_jsonable


class AttemptStatus(models.TextChoices):
    """Status lifecycle for individual service call attempts."""

    BUILT = "built", "Built"  # Request constructed
    DISPATCHED = "dispatched", "Dispatched"  # Sent to provider
    RECEIVED = "received", "Received"  # Response received (pre-validation)
    SCHEMA_OK = "schema_ok", "Schema OK"  # Schema validation passed (winner)
    ERROR = "error", "Error"  # Execution failed
    TIMEOUT = "timeout", "Timeout"  # Provider timeout


class CallStatus(models.TextChoices):
    """Overall status for service call records."""

    PENDING = "pending", "Pending"  # Call created, no attempt started
    IN_PROGRESS = "in_progress", "In Progress"  # At least one attempt running
    COMPLETED = "completed", "Completed"  # Successful attempt
    FAILED = "failed", "Failed"  # All attempts exhausted


class TimestampedModel(models.Model):
    """Abstract base with created/updated timestamps (UTC)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


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

    # Winner tracking
    successful_attempt = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Attempt number that succeeded",
    )
    provider_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="Provider response ID from winning attempt",
    )

    # Continuation for multi-turn conversations
    provider_previous_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Previous response ID passed to provider",
    )

    # Domain linkage
    related_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="ID of related domain object (e.g., simulation_id)",
    )

    # Umbrella correlation
    correlation_id = models.UUIDField(
        default=uuid4,
        db_index=True,
        help_text="Correlation ID for tracing across requests",
    )

    class Meta:
        db_table = "service_call_record"
        indexes = [
            models.Index(fields=["service_identity", "backend"]),
            models.Index(fields=["queue"]),
            models.Index(fields=["status", "domain_persisted", "finished_at"]),
            models.Index(fields=["related_object_id", "status", "-finished_at"]),
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

    def update_from_call(self, call: ServiceCallDataclass) -> None:
        """Synchronize stored fields from a :class:`ServiceCallDataclass`."""

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

    def as_call(self) -> ServiceCallDataclass:
        """Rehydrate a :class:`ServiceCallDataclass` from the persisted payload."""

        dispatch = dict(self.dispatch or {})
        dispatch.setdefault("backend", self.backend)
        if self.queue:
            dispatch.setdefault("queue", self.queue)
        if self.task_id:
            dispatch.setdefault("task_id", self.task_id)

        call = ServiceCallDataclass(
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

    def allocate_attempt(self) -> "ServiceCallAttempt":
        """Atomically allocate next attempt number.

        Must be called within a transaction with select_for_update() on the record.

        Raises:
            AttemptAllocationError: If call is already completed.

        Returns:
            ServiceCallAttempt: The newly created attempt record.
        """
        from django.db import transaction

        if self.status == CallStatus.COMPLETED:
            raise AttemptAllocationError("Call already completed")

        # Compute next attempt number
        max_attempt = self.attempts.aggregate(Max("attempt"))["attempt__max"] or 0
        next_attempt = max_attempt + 1

        # Create attempt record
        attempt = ServiceCallAttempt.objects.create(
            service_call=self,
            attempt=next_attempt,
            status=AttemptStatus.BUILT,
        )

        return attempt

    def mark_attempt_successful(self, attempt: "ServiceCallAttempt", result: dict, provider_response_id: str | None = None) -> None:
        """Atomically mark attempt as winner.

        Must be called within a transaction with select_for_update() on the record.

        Args:
            attempt: The attempt that succeeded.
            result: The result dict to store.
            provider_response_id: Optional provider response ID from the attempt.

        Raises:
            AlreadySucceededError: If call already has a successful attempt.
        """
        if self.successful_attempt is not None:
            raise AlreadySucceededError(f"Call already succeeded with attempt {self.successful_attempt}")

        # Mark attempt
        attempt.status = AttemptStatus.SCHEMA_OK
        attempt.save(update_fields=["status", "updated_at"])

        # Mark call as succeeded
        self.successful_attempt = attempt.attempt
        self.provider_response_id = provider_response_id or attempt.provider_response_id
        self.result = result
        self.status = CallStatus.COMPLETED
        self.finished_at = timezone.now()
        self.save(update_fields=[
            "successful_attempt", "provider_response_id", "result",
            "status", "finished_at", "updated_at"
        ])

    def __str__(self) -> str:  # pragma: no cover
        return f"ServiceCallRecord(id={self.pk}, service={self.service_identity}, status={self.status})"


class AttemptAllocationError(Exception):
    """Raised when attempt allocation fails."""
    pass


class AlreadySucceededError(Exception):
    """Raised when trying to mark success on an already-succeeded call."""
    pass


class ServiceCallAttempt(TimestampedModel):
    """Single execution attempt of a service call.

    Represents one attempt to execute a service call, including the request
    sent to the provider and the response received. Multiple attempts may
    exist for a single ServiceCallRecord due to retries.

    Lifecycle:
        1. Created with status=BUILT when request is constructed
        2. Updated to DISPATCHED when sent to provider
        3. Updated to RECEIVED when response comes back
        4. Updated to SCHEMA_OK if validation passes (winner)
        5. Updated to ERROR/TIMEOUT if something fails

    Key Concept:
        Only ONE attempt per ServiceCallRecord should reach SCHEMA_OK status.
        This is the "winning" attempt whose result is stored in the parent record.
    """

    # Identity
    service_call = models.ForeignKey(
        ServiceCallRecord,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    attempt = models.PositiveIntegerField(help_text="1-indexed attempt number")
    attempt_correlation_id = models.UUIDField(
        default=uuid4,
        db_index=True,
        help_text="Unique correlation ID for this attempt",
    )

    # Status lifecycle
    status = models.CharField(
        max_length=32,
        choices=AttemptStatus.choices,
        default=AttemptStatus.BUILT,
    )

    # Request fields (nullable until request built)
    request_raw = models.JSONField(
        null=True,
        blank=True,
        help_text="Full Request JSON",
    )
    request_messages = models.JSONField(
        default=list,
        help_text="Extracted input messages for querying",
    )
    request_tools = models.JSONField(
        null=True,
        blank=True,
        help_text="Tools passed to provider",
    )
    request_schema_identity = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Identity of the response schema requested",
    )
    request_model = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Model requested for this attempt",
    )

    # Response fields (nullable until response received)
    response_raw = models.JSONField(
        null=True,
        blank=True,
        help_text="Full OrchestrAI Response JSON",
    )
    response_provider_raw = models.JSONField(
        null=True,
        blank=True,
        help_text="Untouched provider response before normalization",
    )
    provider_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Provider's response ID (e.g., OpenAI response ID)",
    )
    structured_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Validated structured output from response",
    )
    finish_reason = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Provider's finish reason",
    )

    # Token usage
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)

    # Timestamps
    dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When request was sent to provider",
    )
    received_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When response was received from provider",
    )

    # Error tracking
    error = models.TextField(
        null=True,
        blank=True,
        help_text="Error message if attempt failed",
    )
    is_retryable = models.BooleanField(
        default=True,
        help_text="Whether this error should trigger a retry",
    )

    # Streaming support
    is_streaming = models.BooleanField(
        default=False,
        help_text="Whether this attempt used streaming",
    )

    class Meta:
        db_table = "service_call_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=["service_call", "attempt"],
                name="unique_call_attempt",
            )
        ]
        indexes = [
            models.Index(fields=["service_call", "attempt"]),
            models.Index(fields=["status"]),
            models.Index(fields=["attempt_correlation_id"]),
            models.Index(fields=["dispatched_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ServiceCallAttempt(call={self.service_call_id}, attempt={self.attempt}, status={self.status})"

    def mark_dispatched(self) -> None:
        """Mark this attempt as dispatched to the provider."""
        self.status = AttemptStatus.DISPATCHED
        self.dispatched_at = timezone.now()
        self.save(update_fields=["status", "dispatched_at", "updated_at"])

    def mark_received(self, response_raw: dict | None = None) -> None:
        """Mark this attempt as having received a response."""
        self.status = AttemptStatus.RECEIVED
        self.received_at = timezone.now()
        if response_raw is not None:
            self.response_raw = response_raw
        self.save(update_fields=["status", "received_at", "response_raw", "updated_at"])

    def mark_error(self, error: str, is_retryable: bool = True) -> None:
        """Mark this attempt as failed."""
        self.status = AttemptStatus.ERROR
        self.error = error
        self.is_retryable = is_retryable
        self.save(update_fields=["status", "error", "is_retryable", "updated_at"])

    def mark_timeout(self) -> None:
        """Mark this attempt as timed out."""
        self.status = AttemptStatus.TIMEOUT
        self.error = "Request timed out"
        self.is_retryable = True
        self.save(update_fields=["status", "error", "is_retryable", "updated_at"])


class ServiceCall(TimestampedModel):
    """
    Unified service call model for Pydantic AI migration.

    Replaces ServiceCallRecord + ServiceCallAttempt with a single model
    that stores Pydantic AI RunResult data directly.

    This model supports:
    - Single-attempt execution (most common case)
    - Pydantic AI RunResult storage
    - Token usage tracking
    - Domain persistence (two-phase commit)
    - Multi-turn conversation via OpenAI response IDs

    Migration Note:
        This model coexists with ServiceCallRecord and ServiceCallAttempt
        during the migration period. New services using DjangoBaseService
        should use this model. Legacy services continue using ServiceCallRecord.
    """

    id = models.CharField(primary_key=True, max_length=64)

    # Service identity
    service_identity = models.CharField(max_length=255, db_index=True)
    service_kwargs = models.JSONField(default=dict)

    # Status lifecycle: pending -> running -> completed/failed
    status = models.CharField(
        max_length=32,
        choices=CallStatus.choices,
        default=CallStatus.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Input
    input = models.JSONField(default=dict)
    context = models.JSONField(null=True, blank=True)

    # Output (from Pydantic AI RunResult)
    output_data = models.JSONField(
        null=True,
        blank=True,
        help_text="result.output serialized - the validated schema data",
    )
    messages_json = models.JSONField(
        default=list,
        help_text="result.new_messages() for conversation continuation",
    )
    usage_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Full RunUsage data",
    )
    model_name = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Model used for this call",
    )

    # Token usage (denormalized for efficient querying)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)

    # Error tracking
    error = models.TextField(null=True, blank=True)

    # Domain persistence (two-phase commit)
    domain_persisted = models.BooleanField(default=False)
    domain_persist_error = models.TextField(null=True, blank=True)

    # OpenAI continuation (for multi-turn conversations)
    openai_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="OpenAI response ID for conversation continuation",
    )

    # Correlation
    correlation_id = models.UUIDField(
        default=uuid4,
        db_index=True,
        help_text="Correlation ID for tracing",
    )
    related_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="ID of related domain object (e.g., simulation_id)",
    )

    # Schema class for declarative persistence
    schema_fqn = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="Fully-qualified name of the Pydantic schema (e.g. chatlab.orca.schemas.patient.PatientInitialOutputSchema)",
    )

    # Task tracking (if using Celery/Django Tasks)
    backend = models.CharField(max_length=64, default="immediate")
    task_id = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        db_table = "service_call"
        indexes = [
            models.Index(fields=["service_identity", "status"]),
            models.Index(fields=["status", "domain_persisted"]),
            models.Index(fields=["related_object_id", "-finished_at"]),
        ]

    def __str__(self) -> str:
        return f"ServiceCall(id={self.pk}, service={self.service_identity}, status={self.status})"

    def to_jsonable(self) -> dict:
        """Export the service call as a JSON-serializable dict."""
        from orchestrai.utils.json import make_json_safe
        return make_json_safe({
            "id": self.id,
            "service_identity": self.service_identity,
            "status": self.status,
            "input": self.input,
            "context": self.context,
            "output_data": self.output_data,
            "messages_json": self.messages_json,
            "usage_json": self.usage_json,
            "model_name": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "error": self.error,
            "domain_persisted": self.domain_persisted,
            "correlation_id": str(self.correlation_id),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        })

    def mark_running(self) -> None:
        """Mark the call as running."""
        self.status = CallStatus.IN_PROGRESS
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    def mark_completed(
        self,
        *,
        output_data: dict | None = None,
        messages_json: list | None = None,
        usage_json: dict | None = None,
        model_name: str | None = None,
        openai_response_id: str | None = None,
    ) -> None:
        """Mark the call as completed with result data."""
        self.status = CallStatus.COMPLETED
        self.finished_at = timezone.now()
        if output_data is not None:
            self.output_data = output_data
        if messages_json is not None:
            self.messages_json = messages_json
        if usage_json is not None:
            self.usage_json = usage_json
            # Extract token counts
            self.input_tokens = usage_json.get("input_tokens", 0) or 0
            self.output_tokens = usage_json.get("output_tokens", 0) or 0
            self.total_tokens = usage_json.get("total_tokens", 0) or 0
        if model_name is not None:
            self.model_name = model_name
        if openai_response_id is not None:
            self.openai_response_id = openai_response_id
        self.save()

    def mark_failed(self, error: str) -> None:
        """Mark the call as failed with an error message."""
        self.status = CallStatus.FAILED
        self.finished_at = timezone.now()
        self.error = error
        self.save(update_fields=["status", "finished_at", "error", "updated_at"])



# PersistedChunk model removed — idempotency now handled by
# ServiceCall.domain_persisted flag + select_for_update().
