# Generated migration for ServiceCallAttempt model and ServiceCallRecord updates
import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("orchestrai_django", "0005_add_ai_audit_models"),
    ]

    operations = [
        # Add new fields to ServiceCallRecord
        migrations.AddField(
            model_name="servicecallrecord",
            name="successful_attempt",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Attempt number that succeeded",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="servicecallrecord",
            name="provider_response_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Provider response ID from winning attempt",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="servicecallrecord",
            name="provider_previous_response_id",
            field=models.CharField(
                blank=True,
                help_text="Previous response ID passed to provider",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="servicecallrecord",
            name="related_object_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="ID of related domain object (e.g., simulation_id)",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="servicecallrecord",
            name="correlation_id",
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                help_text="Correlation ID for tracing across requests",
            ),
        ),
        # Add new index to ServiceCallRecord
        migrations.AddIndex(
            model_name="servicecallrecord",
            index=models.Index(
                fields=["related_object_id", "status", "-finished_at"],
                name="service_cal_related_3f5d8a_idx",
            ),
        ),
        # Create ServiceCallAttempt model
        migrations.CreateModel(
            name="ServiceCallAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "attempt",
                    models.PositiveIntegerField(help_text="1-indexed attempt number"),
                ),
                (
                    "attempt_correlation_id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        help_text="Unique correlation ID for this attempt",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("built", "Built"),
                            ("dispatched", "Dispatched"),
                            ("received", "Received"),
                            ("schema_ok", "Schema OK"),
                            ("error", "Error"),
                            ("timeout", "Timeout"),
                        ],
                        default="built",
                        max_length=32,
                    ),
                ),
                (
                    "request_raw",
                    models.JSONField(
                        blank=True,
                        help_text="Full Request JSON",
                        null=True,
                    ),
                ),
                (
                    "request_messages",
                    models.JSONField(
                        default=list,
                        help_text="Extracted input messages for querying",
                    ),
                ),
                (
                    "request_tools",
                    models.JSONField(
                        blank=True,
                        help_text="Tools passed to provider",
                        null=True,
                    ),
                ),
                (
                    "request_schema_identity",
                    models.CharField(
                        blank=True,
                        help_text="Identity of the response schema requested",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "request_model",
                    models.CharField(
                        blank=True,
                        help_text="Model requested for this attempt",
                        max_length=128,
                        null=True,
                    ),
                ),
                (
                    "response_raw",
                    models.JSONField(
                        blank=True,
                        help_text="Full OrchestrAI Response JSON",
                        null=True,
                    ),
                ),
                (
                    "response_provider_raw",
                    models.JSONField(
                        blank=True,
                        help_text="Untouched provider response before normalization",
                        null=True,
                    ),
                ),
                (
                    "provider_response_id",
                    models.CharField(
                        blank=True,
                        help_text="Provider's response ID (e.g., OpenAI response ID)",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "structured_data",
                    models.JSONField(
                        blank=True,
                        help_text="Validated structured output from response",
                        null=True,
                    ),
                ),
                (
                    "finish_reason",
                    models.CharField(
                        blank=True,
                        help_text="Provider's finish reason",
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "input_tokens",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "output_tokens",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "total_tokens",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "reasoning_tokens",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "dispatched_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When request was sent to provider",
                        null=True,
                    ),
                ),
                (
                    "received_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When response was received from provider",
                        null=True,
                    ),
                ),
                (
                    "error",
                    models.TextField(
                        blank=True,
                        help_text="Error message if attempt failed",
                        null=True,
                    ),
                ),
                (
                    "is_retryable",
                    models.BooleanField(
                        default=True,
                        help_text="Whether this error should trigger a retry",
                    ),
                ),
                (
                    "is_streaming",
                    models.BooleanField(
                        default=False,
                        help_text="Whether this attempt used streaming",
                    ),
                ),
                (
                    "service_call",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="orchestrai_django.servicecallrecord",
                    ),
                ),
            ],
            options={
                "db_table": "service_call_attempt",
            },
        ),
        # Add constraints and indexes to ServiceCallAttempt
        migrations.AddConstraint(
            model_name="servicecallattempt",
            constraint=models.UniqueConstraint(
                fields=("service_call", "attempt"),
                name="unique_call_attempt",
            ),
        ),
        migrations.AddIndex(
            model_name="servicecallattempt",
            index=models.Index(
                fields=["service_call", "attempt"],
                name="service_cal_service_a2d3f1_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="servicecallattempt",
            index=models.Index(
                fields=["status"],
                name="service_cal_status_e8c7b2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="servicecallattempt",
            index=models.Index(
                fields=["attempt_correlation_id"],
                name="service_cal_attempt_f1a9c3_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="servicecallattempt",
            index=models.Index(
                fields=["dispatched_at"],
                name="service_cal_dispatc_7b4e2a_idx",
            ),
        ),
    ]
