# orchestrai_django/models.py
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Max, Sum
from django.utils import timezone
from django.utils.functional import cached_property


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


class Backend(models.TextChoices):
    """Execution backend for service calls."""

    IMMEDIATE = "immediate", "Immediate"
    CELERY = "celery", "Celery"
    DJANGO_TASKS = "django_tasks", "Django Tasks"


class TimestampedModel(models.Model):
    """Abstract base with created/updated timestamps (UTC)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AttemptAllocationError(Exception):
    """Raised when attempt allocation fails."""
    pass


class AlreadySucceededError(Exception):
    """Raised when trying to mark success on an already-succeeded call."""
    pass


class ServiceCallQuerySet(models.QuerySet):
    """Custom queryset for ServiceCall with common query patterns."""

    def completed(self):
        """Return only completed calls."""
        return self.filter(status=CallStatus.COMPLETED)

    def failed(self):
        """Return only failed calls."""
        return self.filter(status=CallStatus.FAILED)

    def pending(self):
        """Return only pending calls."""
        return self.filter(status=CallStatus.PENDING)

    def in_progress(self):
        """Return only in-progress calls."""
        return self.filter(status=CallStatus.IN_PROGRESS)

    def pending_persistence(self):
        """Return calls awaiting domain persistence."""
        return self.filter(
            status=CallStatus.COMPLETED,
            domain_persisted=False,
        ).exclude(schema_fqn__isnull=True).exclude(schema_fqn='')

    def for_simulation(self, simulation_id):
        """Return calls for a specific simulation."""
        return self.filter(related_object_id=str(simulation_id))

    def with_retries(self):
        """Return calls that required multiple attempts."""
        return self.annotate(
            attempt_count=Count('attempts')
        ).filter(attempt_count__gt=1)

    def by_service(self, service_identity):
        """Return calls for a specific service."""
        return self.filter(service_identity=service_identity)


class ServiceCallManager(models.Manager):
    """Custom manager for ServiceCall with convenience methods."""

    def get_queryset(self):
        return ServiceCallQuerySet(self.model, using=self._db)

    def completed(self):
        return self.get_queryset().completed()

    def failed(self):
        return self.get_queryset().failed()

    def pending(self):
        return self.get_queryset().pending()

    def in_progress(self):
        return self.get_queryset().in_progress()

    def pending_persistence(self):
        return self.get_queryset().pending_persistence()

    def for_simulation(self, simulation_id):
        return self.get_queryset().for_simulation(simulation_id)

    def with_retries(self):
        return self.get_queryset().with_retries()

    def by_service(self, service_identity):
        return self.get_queryset().by_service(service_identity)


class ServiceCall(TimestampedModel):
    """
    Unified service call model.

    This model stores all service call data including:
    - Service identity and execution state
    - Pydantic AI RunResult data
    - Attempt tracking (via ServiceCallAttempt FK)
    - Token usage
    - Domain persistence (two-phase commit)
    - Multi-turn conversation via OpenAI response IDs
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    # Service identity
    service_identity = models.CharField(max_length=255, db_index=True)
    service_kwargs = models.JSONField(default=dict)

    # Status lifecycle: pending -> in_progress -> completed/failed
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
    request = models.JSONField(
        null=True,
        blank=True,
        help_text="Full request JSON (debugging)",
    )

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
    reasoning_tokens = models.PositiveIntegerField(default=0)

    # Cost tracking (future-proof)
    input_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Cost in USD for input tokens"
    )
    output_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Cost in USD for output tokens"
    )
    total_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Total cost in USD"
    )

    # Error tracking
    error = models.TextField(null=True, blank=True)

    # Domain persistence (two-phase commit)
    domain_persisted = models.BooleanField(default=False)
    domain_persist_error = models.TextField(null=True, blank=True)
    domain_persist_attempts = models.PositiveIntegerField(default=0)

    # Winner tracking
    successful_attempt = models.ForeignKey(
        'ServiceCallAttempt',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='won_call',
        help_text="The attempt that succeeded",
    )

    # OpenAI continuation (for multi-turn conversations)
    provider_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="OpenAI response ID for conversation continuation",
    )

    # Continuation for multi-turn conversations (inbound)
    previous_provider_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Previous response ID passed to provider",
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
    backend = models.CharField(
        max_length=64,
        choices=Backend.choices,
        default=Backend.IMMEDIATE
    )
    queue = models.CharField(max_length=128, null=True, blank=True)
    task_id = models.CharField(max_length=128, null=True, blank=True)

    # Dispatch metadata
    dispatch = models.JSONField(default=dict)

    # Custom manager
    objects = ServiceCallManager()

    class Meta:
        db_table = "service_call"
        verbose_name = "Service Call"
        verbose_name_plural = "Service Calls"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["service_identity", "status"]),
            models.Index(fields=["status", "domain_persisted", "finished_at"]),
            models.Index(fields=["related_object_id", "-finished_at"]),
            models.Index(fields=["related_object_id", "status", "-finished_at"]),
            # Additional indexes for common patterns
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['service_identity', 'status', '-created_at']),
            models.Index(fields=['provider_response_id']),
            models.Index(fields=['schema_fqn', 'status']),
        ]

    def __str__(self) -> str:
        return f"ServiceCall(id={self.pk}, service={self.service_identity}, status={self.status})"

    def __repr__(self) -> str:
        return (
            f"<ServiceCall id={self.pk!r} "
            f"service={self.service_identity!r} "
            f"status={self.status!r}>"
        )

    # Convenience properties for accessing attempts
    @cached_property
    def latest_attempt(self):
        """Get the most recent attempt."""
        return self.attempts.order_by('-attempt').first()

    @cached_property
    def final_attempt(self):
        """Alias for latest_attempt (more semantic for completed calls)."""
        return self.latest_attempt

    @cached_property
    def winning_attempt(self):
        """Get the attempt that succeeded (status=SCHEMA_OK)."""
        if self.successful_attempt:
            return self.successful_attempt
        return self.attempts.filter(status=AttemptStatus.SCHEMA_OK).first()

    @property
    def successful_attempt_number(self) -> int | None:
        """Get the attempt number that succeeded (for backward compatibility)."""
        return self.successful_attempt.attempt if self.successful_attempt else None

    # Duration properties
    @property
    def duration(self) -> timedelta | None:
        """Total execution time."""
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    @property
    def duration_seconds(self) -> float | None:
        """Total execution time in seconds."""
        if self.duration:
            return self.duration.total_seconds()
        return None

    @property
    def duration_ms(self) -> float | None:
        """Total execution time in milliseconds."""
        if self.duration:
            return self.duration.total_seconds() * 1000
        return None

    # Status check properties
    @property
    def is_complete(self) -> bool:
        """Check if call is completed."""
        return self.status == CallStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Check if call failed."""
        return self.status == CallStatus.FAILED

    @property
    def is_pending(self) -> bool:
        """Check if call is pending."""
        return self.status == CallStatus.PENDING

    @property
    def is_running(self) -> bool:
        """Check if call is in progress."""
        return self.status == CallStatus.IN_PROGRESS

    # Observability helpers
    @property
    def trace_id(self) -> str:
        """OpenTelemetry-compatible trace ID."""
        return str(self.correlation_id)

    @property
    def span_id(self) -> str:
        """OpenTelemetry-compatible span ID."""
        return str(self.id)

    def to_span_attributes(self) -> dict:
        """Export as OpenTelemetry span attributes."""
        return {
            'service.call.id': str(self.id),
            'service.identity': self.service_identity,
            'service.status': self.status,
            'service.input_tokens': self.input_tokens,
            'service.output_tokens': self.output_tokens,
            'service.total_tokens': self.total_tokens,
            'service.reasoning_tokens': self.reasoning_tokens,
            'service.duration_ms': self.duration_ms,
            'service.backend': self.backend,
            'service.model': self.model_name,
            'service.correlation_id': str(self.correlation_id),
        }

    def to_dict(self) -> dict:
        """Return as dict with Python objects (datetimes, etc.)."""
        return {
            'id': self.id,
            'service_identity': self.service_identity,
            'status': self.status,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'finished_at': self.finished_at,
            'duration_seconds': self.duration_seconds,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'total_tokens': self.total_tokens,
            'reasoning_tokens': self.reasoning_tokens,
            'output_data': self.output_data,
            'error': self.error,
            'backend': self.backend,
            'model_name': self.model_name,
            'correlation_id': self.correlation_id,
        }

    def to_jsonable(self) -> dict:
        """Export the service call as a JSON-serializable dict."""
        from orchestrai.utils import make_json_safe
        data = self.to_dict()
        # Convert datetime objects to ISO strings
        for key in ('created_at', 'started_at', 'finished_at'):
            if data[key]:
                data[key] = data[key].isoformat()
        # Convert UUID to string
        data['id'] = str(data['id'])
        data['correlation_id'] = str(data['correlation_id'])
        return make_json_safe(data)

    def clean(self):
        """Validate model state before saving."""
        super().clean()

        # Validate that successful calls have output_data
        if self.status == CallStatus.COMPLETED and not self.output_data:
            raise ValidationError({
                'output_data': 'Completed calls must have output_data'
            })

        # Validate that failed calls have error message
        if self.status == CallStatus.FAILED and not self.error:
            raise ValidationError({
                'error': 'Failed calls must have error message'
            })

        # Validate successful_attempt exists if status is COMPLETED
        if self.status == CallStatus.COMPLETED and not self.successful_attempt:
            raise ValidationError({
                'successful_attempt': 'Completed calls must have successful_attempt set'
            })

    def get_absolute_url(self):
        """Get Django admin URL for this object."""
        from django.urls import reverse
        return reverse('admin:orchestrai_django_servicecall_change', args=[str(self.pk)])

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
        provider_response_id: str | None = None,
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
        if provider_response_id is not None:
            self.provider_response_id = provider_response_id
        self.save()

    def mark_failed(self, error: str) -> None:
        """Mark the call as failed with an error message."""
        self.status = CallStatus.FAILED
        self.finished_at = timezone.now()
        self.error = error
        self.save(update_fields=["status", "finished_at", "error", "updated_at"])

    def allocate_attempt(self) -> "ServiceCallAttempt":
        """Atomically allocate next attempt number.

        Must be called within a transaction with select_for_update() on the record.

        Raises:
            AttemptAllocationError: If call is already completed.

        Returns:
            ServiceCallAttempt: The newly created attempt record.
        """
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

    def mark_attempt_successful(
        self,
        attempt: "ServiceCallAttempt",
        output_data: dict | None,
        provider_response_id: str | None = None,
    ) -> None:
        """Atomically mark attempt as winner.

        Must be called within a transaction with select_for_update() on the record.

        Args:
            attempt: The attempt that succeeded.
            output_data: The validated output data to store.
            provider_response_id: Optional provider response ID from the attempt.

        Raises:
            AlreadySucceededError: If call already has a successful attempt.
        """
        if self.successful_attempt is not None:
            raise AlreadySucceededError(f"Call already succeeded with attempt {self.successful_attempt.attempt}")

        # Mark attempt
        attempt.status = AttemptStatus.SCHEMA_OK
        attempt.save(update_fields=["status", "updated_at"])

        # Mark call as succeeded (now using FK)
        self.successful_attempt = attempt
        self.provider_response_id = provider_response_id or attempt.provider_response_id
        self.output_data = output_data
        self.status = CallStatus.COMPLETED
        self.finished_at = timezone.now()

        # Aggregate token usage from attempts
        attempt_totals = self.attempts.aggregate(
            total_input=Sum('input_tokens'),
            total_output=Sum('output_tokens'),
            total_all=Sum('total_tokens'),
            total_reasoning=Sum('reasoning_tokens'),
        )
        self.input_tokens = attempt_totals['total_input'] or 0
        self.output_tokens = attempt_totals['total_output'] or 0
        self.total_tokens = attempt_totals['total_all'] or 0
        self.reasoning_tokens = attempt_totals['total_reasoning'] or 0

        self.save(update_fields=[
            "successful_attempt", "provider_response_id", "output_data",
            "status", "finished_at", "input_tokens", "output_tokens",
            "total_tokens", "reasoning_tokens", "updated_at"
        ])

    @classmethod
    def retry_failed_persistence(cls, max_age_hours: int = 24) -> int:
        """Bulk retry failed domain persistence.

        Resets domain_persist_attempts to 0 for calls that failed persistence
        but are within the max_age_hours window.

        Args:
            max_age_hours: Only retry calls finished within this many hours.

        Returns:
            Number of calls marked for retry.
        """
        cutoff = timezone.now() - timedelta(hours=max_age_hours)
        qs = cls.objects.filter(
            status=CallStatus.COMPLETED,
            domain_persisted=False,
            domain_persist_attempts__lt=10,
            finished_at__gte=cutoff,
        ).exclude(schema_fqn__isnull=True).exclude(schema_fqn='')

        count = qs.update(
            domain_persist_attempts=0,
            domain_persist_error=None,
        )
        return count


class ServiceCallAttempt(TimestampedModel):
    """Single execution attempt of a service call.

    Represents one attempt to execute a service call, including the request
    sent to the provider and the response received. Multiple attempts may
    exist for a single ServiceCall due to retries.

    Lifecycle:
        1. Created with status=BUILT when request is constructed
        2. Updated to DISPATCHED when sent to provider
        3. Updated to RECEIVED when response comes back
        4. Updated to SCHEMA_OK if validation passes (winner)
        5. Updated to ERROR/TIMEOUT if something fails

    Key Concept:
        Only ONE attempt per ServiceCall should reach SCHEMA_OK status.
        This is the "winning" attempt whose result is stored in the parent call.
    """

    # Identity
    service_call = models.ForeignKey(
        ServiceCall,
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

    # Request fields - consolidated and clarified naming
    request_input = models.JSONField(
        null=True,
        blank=True,
        help_text="SimWorks request JSON (high-level service input)",
    )
    request_pydantic = models.JSONField(
        null=True,
        blank=True,
        help_text="Pydantic AI Request object (pre-provider normalization)",
    )
    request_provider = models.JSONField(
        null=True,
        blank=True,
        help_text="Final request JSON sent to provider (OpenAI/Anthropic format)",
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
    schema_fqn = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Fully-qualified Python name of the response schema",
    )
    request_model = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Model requested for this attempt",
    )

    # Agent configuration (for debugging)
    agent_config = models.JSONField(
        null=True,
        blank=True,
        help_text="Pydantic AI Agent configuration (model, settings, system prompts, tools)",
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
    previous_provider_response_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Previous provider response ID attached to this request",
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
        verbose_name = "Service Call Attempt"
        verbose_name_plural = "Service Call Attempts"
        ordering = ['service_call', 'attempt']
        constraints = [
            models.UniqueConstraint(
                fields=["service_call", "attempt"],
                name="unique_call_attempt",
            ),
            # Ensure only one SCHEMA_OK attempt per call
            models.UniqueConstraint(
                fields=["service_call"],
                condition=models.Q(status=AttemptStatus.SCHEMA_OK),
                name="unique_schema_ok_per_call",
            ),
        ]
        indexes = [
            models.Index(fields=["service_call", "attempt"]),
            models.Index(fields=["status"]),
            models.Index(fields=["attempt_correlation_id"]),
            models.Index(fields=["dispatched_at"]),
            models.Index(fields=["received_at"]),
            models.Index(fields=["service_call", "status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ServiceCallAttempt(call={self.service_call_id}, attempt={self.attempt}, status={self.status})"

    def __repr__(self) -> str:
        return (
            f"<ServiceCallAttempt call={self.service_call_id!r} "
            f"attempt={self.attempt} status={self.status!r}>"
        )

    # Duration properties
    @property
    def duration(self) -> timedelta | None:
        """Execution duration (dispatch to receive)."""
        if self.dispatched_at and self.received_at:
            return self.received_at - self.dispatched_at
        return None

    @property
    def duration_ms(self) -> float | None:
        """Execution duration in milliseconds."""
        if self.duration:
            return self.duration.total_seconds() * 1000
        return None

    @property
    def duration_seconds(self) -> float | None:
        """Execution duration in seconds."""
        if self.duration:
            return self.duration.total_seconds()
        return None

    # Status check properties
    @property
    def is_successful(self) -> bool:
        """Check if this attempt succeeded."""
        return self.status == AttemptStatus.SCHEMA_OK

    @property
    def is_error(self) -> bool:
        """Check if this attempt errored."""
        return self.status == AttemptStatus.ERROR

    @property
    def is_timeout(self) -> bool:
        """Check if this attempt timed out."""
        return self.status == AttemptStatus.TIMEOUT

    def get_absolute_url(self):
        """Get Django admin URL for this object."""
        from django.urls import reverse
        return reverse('admin:orchestrai_django_servicecallattempt_change', args=[self.pk])

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
