import json
from typing import Any

from django.contrib import admin
from django.utils import timezone as tz_
from django.utils.html import format_html

from .models import AIRequestAudit, AIResponseAudit, ServiceCallRecord, PersistedChunk


# ----------------------------- helpers ---------------------------------


def _short_json(value: Any, max_chars: int = 160) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(value)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def _pretty_json(value: Any) -> str:
    """Format JSON for display in admin detail view."""
    try:
        return format_html(
            "<pre style='white-space: pre-wrap; max-height: 400px; overflow-y: auto;'>{}</pre>",
            json.dumps(value, indent=2, ensure_ascii=False),
        )
    except Exception:
        return str(value)


# ----------------------------- ModelAdmins ------------------------------


@admin.register(AIRequestAudit)
class AIRequestAuditAdmin(admin.ModelAdmin):
    """Admin for AI request audit records."""

    list_display = (
        "id",
        "created_at",
        "service_identity",
        "namespace",
        "provider_name",
        "model",
        "correlation_id_short",
        "dispatched_at",
        "attempts",
    )
    list_filter = (
        "provider_name",
        "namespace",
        ("dispatched_at", admin.EmptyFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "id",
        "correlation_id",
        "service_identity",
        "namespace",
        "provider_name",
        "model",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    raw_id_fields = ("service_call",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "correlation_id",
        "service_identity",
        "namespace",
        "kind",
        "name",
        "provider_name",
        "client_name",
        "model",
        "raw_pretty",
        "messages_pretty",
        "tools_pretty",
        "response_schema_identity",
        "object_db_pk",
        "dispatched_at",
        "attempts",
        "next_attempt_at",
        "last_error",
    )
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    ("created_at", "updated_at"),
                    "correlation_id",
                    ("service_identity", "service_call"),
                    ("namespace", "kind", "name"),
                )
            },
        ),
        (
            "Provider",
            {
                "fields": (
                    ("provider_name", "client_name"),
                    "model",
                )
            },
        ),
        (
            "Request Data",
            {
                "fields": (
                    "response_schema_identity",
                    "messages_pretty",
                    "tools_pretty",
                    "raw_pretty",
                )
            },
        ),
        (
            "Linkage",
            {
                "fields": ("object_db_pk",)
            },
        ),
        (
            "Dispatch Tracking",
            {
                "fields": (
                    ("dispatched_at", "attempts"),
                    "next_attempt_at",
                    "last_error",
                )
            },
        ),
    )

    @admin.display(description="Correlation ID")
    def correlation_id_short(self, obj: AIRequestAudit) -> str:
        return str(obj.correlation_id)[:8] + "..."

    @admin.display(description="Raw Request")
    def raw_pretty(self, obj: AIRequestAudit) -> str:
        return _pretty_json(obj.raw)

    @admin.display(description="Messages")
    def messages_pretty(self, obj: AIRequestAudit) -> str:
        return _pretty_json(obj.messages)

    @admin.display(description="Tools")
    def tools_pretty(self, obj: AIRequestAudit) -> str:
        return _pretty_json(obj.tools) if obj.tools else "-"


@admin.register(AIResponseAudit)
class AIResponseAuditAdmin(admin.ModelAdmin):
    """Admin for AI response audit records."""

    list_display = (
        "id",
        "created_at",
        "provider_name",
        "model",
        "finish_reason",
        "total_tokens",
        "correlation_id_short",
        "received_at",
    )
    list_filter = (
        "provider_name",
        "finish_reason",
        ("received_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "id",
        "correlation_id",
        "request_correlation_id",
        "provider_name",
        "model",
        "provider_response_id",
    )
    date_hierarchy = "received_at"
    ordering = ("-received_at", "-id")
    raw_id_fields = ("ai_request", "service_call")
    readonly_fields = (
        "created_at",
        "updated_at",
        "correlation_id",
        "request_correlation_id",
        "provider_name",
        "client_name",
        "model",
        "finish_reason",
        "provider_response_id",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "received_at",
        "raw_pretty",
        "provider_raw_pretty",
        "structured_data_pretty",
        "execution_metadata_pretty",
    )
    fieldsets = (
        (
            "Links",
            {
                "fields": (
                    ("created_at", "updated_at"),
                    ("ai_request", "service_call"),
                    ("correlation_id", "request_correlation_id"),
                )
            },
        ),
        (
            "Provider",
            {
                "fields": (
                    ("provider_name", "client_name"),
                    ("model", "finish_reason"),
                    "provider_response_id",
                )
            },
        ),
        (
            "Usage",
            {
                "fields": (
                    ("input_tokens", "output_tokens"),
                    ("total_tokens", "reasoning_tokens"),
                )
            },
        ),
        (
            "Response Data",
            {
                "fields": (
                    "received_at",
                    "structured_data_pretty",
                    "execution_metadata_pretty",
                    "raw_pretty",
                    "provider_raw_pretty",
                )
            },
        ),
    )

    @admin.display(description="Correlation ID")
    def correlation_id_short(self, obj: AIResponseAudit) -> str:
        return str(obj.correlation_id)[:8] + "..."

    @admin.display(description="Raw Response")
    def raw_pretty(self, obj: AIResponseAudit) -> str:
        return _pretty_json(obj.raw)

    @admin.display(description="Provider Raw")
    def provider_raw_pretty(self, obj: AIResponseAudit) -> str:
        return _pretty_json(obj.provider_raw) if obj.provider_raw else "-"

    @admin.display(description="Structured Data")
    def structured_data_pretty(self, obj: AIResponseAudit) -> str:
        return _pretty_json(obj.structured_data) if obj.structured_data else "-"

    @admin.display(description="Execution Metadata")
    def execution_metadata_pretty(self, obj: AIResponseAudit) -> str:
        return _pretty_json(obj.execution_metadata) if obj.execution_metadata else "-"


@admin.register(ServiceCallRecord)
class ServiceCallRecordAdmin(admin.ModelAdmin):
    """Admin for service call records.

    Future Enhancements (Phase 3):
        - Display related user(s) from the simulation context
        - Show PersistedChunk records linked to this call (domain objects created)
        - Link to related Simulation object via related_object_id
        - Display Message/SimulationMetadata objects created by this call
        - Add filters for related_object_id to find all calls for a simulation
        - Show attempt success/failure timeline visualization
    """

    list_display = (
        "id",
        "created_at",
        "service_identity",
        "status",
        "backend",
        "domain_persisted",
        "finished_at",
    )
    list_filter = (
        "status",
        "backend",
        "domain_persisted",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "id",
        "service_identity",
        "task_id",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "service_identity",
        "status",
        "backend",
        "queue",
        "task_id",
        "started_at",
        "finished_at",
        "domain_persisted",
        "domain_persist_error",
        "domain_persist_attempts",
        "input_pretty",
        "context_pretty",
        "result_pretty",
        "error",
    )
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "id",
                    ("created_at", "updated_at"),
                    "service_identity",
                )
            },
        ),
        (
            "Execution",
            {
                "fields": (
                    "status",
                    ("backend", "queue"),
                    "task_id",
                    ("started_at", "finished_at"),
                )
            },
        ),
        (
            "Domain Persistence",
            {
                "fields": (
                    "domain_persisted",
                    "domain_persist_attempts",
                    "domain_persist_error",
                )
            },
        ),
        (
            "Data",
            {
                "fields": (
                    "input_pretty",
                    "context_pretty",
                    "result_pretty",
                    "error",
                )
            },
        ),
    )

    @admin.display(description="Input")
    def input_pretty(self, obj: ServiceCallRecord) -> str:
        return _pretty_json(obj.input)

    @admin.display(description="Context")
    def context_pretty(self, obj: ServiceCallRecord) -> str:
        return _pretty_json(obj.context) if obj.context else "-"

    @admin.display(description="Result")
    def result_pretty(self, obj: ServiceCallRecord) -> str:
        return _pretty_json(obj.result) if obj.result else "-"


@admin.register(PersistedChunk)
class PersistedChunkAdmin(admin.ModelAdmin):
    """Admin for persisted chunk records."""

    list_display = (
        "id",
        "created_at",
        "call_id",
        "namespace",
        "schema_identity_short",
        "handler_identity_short",
        "content_type",
        "object_id",
    )
    list_filter = (
        "namespace",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "call_id",
        "schema_identity",
        "handler_identity",
        "namespace",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "call_id",
        "schema_identity",
        "namespace",
        "handler_identity",
        "content_type",
        "object_id",
        "persisted_at",
    )

    @admin.display(description="Schema Identity")
    def schema_identity_short(self, obj: PersistedChunk) -> str:
        if len(obj.schema_identity) > 40:
            return obj.schema_identity[:37] + "..."
        return obj.schema_identity

    @admin.display(description="Handler Identity")
    def handler_identity_short(self, obj: PersistedChunk) -> str:
        if len(obj.handler_identity) > 40:
            return obj.handler_identity[:37] + "..."
        return obj.handler_identity
