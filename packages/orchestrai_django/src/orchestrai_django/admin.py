import json
from typing import Any

from django.contrib import admin
from django.utils.html import format_html

from .models import ServiceCall, ServiceCallAttempt


# ----------------------------- helpers ---------------------------------


def _short_json(value: Any, max_chars: int = 160) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(value)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "\u2026"
    return text


def _pretty_json(value: Any) -> str:
    """Format JSON for display in admin detail view."""
    try:
        def _normalize_newlines(text: str) -> str:
            return text.replace("\\n", "\n").replace("/n", "\n")

        def _walk(val: Any) -> Any:
            if isinstance(val, str):
                return _normalize_newlines(val)
            if isinstance(val, list):
                return [_walk(item) for item in val]
            if isinstance(val, dict):
                return {key: _walk(inner) for key, inner in val.items()}
            return val

        value = _walk(value)
        return format_html(
            "<pre style='white-space: pre-wrap; max-height: 400px; overflow-y: auto;'>{}</pre>",
            json.dumps(value, indent=2, ensure_ascii=False),
        )
    except Exception:
        return str(value)


# ----------------------------- ModelAdmins ------------------------------


class ServiceCallAttemptInline(admin.TabularInline):
    """Inline display of attempts for a service call."""

    model = ServiceCallAttempt
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = (
        "attempt",
        "status",
        "dispatched_at",
        "received_at",
        "total_tokens",
        "error",
        "is_retryable",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ServiceCall)
class ServiceCallAdmin(admin.ModelAdmin):
    """Admin for service calls."""

    list_display = (
        "id",
        "created_at",
        "service_identity",
        "status",
        "successful_attempt",
        "backend",
        "domain_persisted",
        "related_object_id",
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
        "correlation_id",
        "related_object_id",
        "provider_response_id",
        "schema_fqn",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = [ServiceCallAttemptInline]
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
        "successful_attempt",
        "provider_response_id",
        "previous_provider_response_id",
        "related_object_id",
        "correlation_id",
        "schema_fqn",
        "input_pretty",
        "context_pretty",
        "request_pretty",
        "output_data_pretty",
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
                    "correlation_id",
                    "schema_fqn",
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
            "Attempt Tracking",
            {
                "fields": (
                    "successful_attempt",
                    "provider_response_id",
                    "previous_provider_response_id",
                )
            },
        ),
        (
            "Domain Linkage",
            {
                "fields": (
                    "related_object_id",
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
                    "request_pretty",
                    "output_data_pretty",
                    "error",
                )
            },
        ),
    )

    @admin.display(description="Input")
    def input_pretty(self, obj: ServiceCall) -> str:
        return _pretty_json(obj.input)

    @admin.display(description="Context")
    def context_pretty(self, obj: ServiceCall) -> str:
        return _pretty_json(obj.context) if obj.context else "-"

    @admin.display(description="Output Data")
    def output_data_pretty(self, obj: ServiceCall) -> str:
        return _pretty_json(obj.output_data) if obj.output_data else "-"

    @admin.display(description="Request JSON")
    def request_pretty(self, obj: ServiceCall) -> str:
        if obj.request:
            return _pretty_json(obj.request)
        latest = obj.latest_attempt
        if latest and latest.request_input:
            return _pretty_json(latest.request_input)
        if latest and latest.request_provider:
            return _pretty_json(latest.request_provider)
        return "-"


@admin.register(ServiceCallAttempt)
class ServiceCallAttemptAdmin(admin.ModelAdmin):
    """Admin for individual service call attempts."""

    list_display = (
        "id",
        "created_at",
        "service_call_link",
        "attempt",
        "status",
        "total_tokens",
        "dispatched_at",
        "received_at",
    )
    list_filter = (
        "status",
        "is_retryable",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "id",
        "service_call__id",
        "service_call__service_identity",
        "attempt_correlation_id",
        "provider_response_id",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-attempt")
    raw_id_fields = ("service_call",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "service_call",
        "attempt",
        "attempt_correlation_id",
        "status",
        "request_input_pretty",
        "request_pydantic_pretty",
        "request_provider_pretty",
        "request_messages_pretty",
        "request_tools_pretty",
        "schema_fqn",
        "request_model",
        "agent_config_pretty",
        "response_raw_pretty",
        "response_provider_raw_pretty",
        "provider_response_id",
        "structured_data_pretty",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "dispatched_at",
        "received_at",
        "error",
        "is_retryable",
        "is_streaming",
    )
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    ("created_at", "updated_at"),
                    "service_call",
                    ("attempt", "attempt_correlation_id"),
                    "status",
                )
            },
        ),
        (
            "Request Pipeline (3 Layers)",
            {
                "fields": (
                    "request_model",
                    "schema_fqn",
                    "request_input_pretty",
                    "request_pydantic_pretty",
                    "request_provider_pretty",
                    "request_messages_pretty",
                    "request_tools_pretty",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Agent Configuration",
            {
                "fields": (
                    "agent_config_pretty",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Response",
            {
                "fields": (
                    ("dispatched_at", "received_at"),
                    ("finish_reason", "provider_response_id"),
                    "is_streaming",
                    "structured_data_pretty",
                    "response_raw_pretty",
                    "response_provider_raw_pretty",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Token Usage",
            {
                "fields": (
                    ("input_tokens", "output_tokens"),
                    ("total_tokens", "reasoning_tokens"),
                )
            },
        ),
        (
            "Error",
            {
                "fields": (
                    "error",
                    "is_retryable",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Service Call")
    def service_call_link(self, obj: ServiceCallAttempt) -> str:
        if obj.service_call:
            return format_html(
                '<a href="/admin/orchestrai_django/servicecall/{}/change/">{}</a>',
                obj.service_call_id,
                obj.service_call_id[:16] + "..." if len(obj.service_call_id) > 16 else obj.service_call_id,
            )
        return "-"

    @admin.display(description="Request Input (SimWorks)")
    def request_input_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.request_input) if obj.request_input else "-"

    @admin.display(description="Request Pydantic (Pydantic AI)")
    def request_pydantic_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.request_pydantic) if obj.request_pydantic else "-"

    @admin.display(description="Request Provider (Wire Format)")
    def request_provider_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.request_provider) if obj.request_provider else "-"

    @admin.display(description="Request Messages")
    def request_messages_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.request_messages) if obj.request_messages else "-"

    @admin.display(description="Request Tools")
    def request_tools_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.request_tools) if obj.request_tools else "-"

    @admin.display(description="Agent Configuration")
    def agent_config_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.agent_config) if obj.agent_config else "-"

    @admin.display(description="Response Raw")
    def response_raw_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.response_raw) if obj.response_raw else "-"

    @admin.display(description="Provider Raw")
    def response_provider_raw_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.response_provider_raw) if obj.response_provider_raw else "-"

    @admin.display(description="Structured Data")
    def structured_data_pretty(self, obj: ServiceCallAttempt) -> str:
        return _pretty_json(obj.structured_data) if obj.structured_data else "-"
