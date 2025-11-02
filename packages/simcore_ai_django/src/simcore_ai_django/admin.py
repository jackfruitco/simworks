

from __future__ import annotations

import json
from typing import Any

from django.contrib import admin
from django.utils.html import format_html

from .models import AIRequestAudit, AIResponseAudit, AIOutbox


# ----------------------------- helpers ---------------------------------

def _short_json(value: Any, max_chars: int = 160) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(value)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


# ----------------------------- inlines ---------------------------------

class AIResponseAuditInline(admin.TabularInline):
    model = AIResponseAudit
    extra = 0
    fields = (
        "id",
        "received_at",
        "status_badge",
        "usage_short",
    )
    readonly_fields = fields
    ordering = ("-received_at",)
    show_change_link = True

    @admin.display(description="Status")
    def status_badge(self, obj: AIResponseAudit) -> str:
        if obj.error:
            return format_html('<span style="color:#b91c1c;">error</span>')
        return format_html('<span style="color:#065f46;">ok</span>')

    @admin.display(description="Usage")
    def usage_short(self, obj: AIResponseAudit) -> str:
        return _short_json(obj.usage)


# ----------------------------- ModelAdmins ------------------------------

@admin.register(AIRequestAudit)
class AIRequestAuditAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "namespace",
        "name",
        "provider_name",
        "client_name",
        "model",
        "stream",
        "correlation_id",
    )
    list_filter = (
        "provider_name",
        "client_name",
        "namespace",
        "kind",
        "name",
        "stream",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "id",
        "correlation_id",
        "namespace",
        "kind",
        "name",
        "provider_name",
        "client_name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    list_per_page = 50

    readonly_fields = (
        "created_at",
        "updated_at",
        "correlation_id",
        "namespace",
        "kind",
        "name",
        "provider_name",
        "client_name",
        "simulation_pk",
        "model",
        "stream",
        "messages_pretty",
        "tools_pretty",
        "response_format_cls",
        "response_format_adapted_pretty",
        "response_format_pretty",
        "prompt_meta_pretty",
    )

    fields = (
        ("created_at", "updated_at"),
        ("name", "provider_name", "client_name"),
        ("namespace", "kind", "simulation_pk", "correlation_id"),
        ("model", "stream"),
        "messages_pretty",
        "tools_pretty",
        "response_format_cls",
        "response_format_adapted_pretty",
        "response_format_pretty",
        "prompt_meta_pretty",
    )

    inlines = [AIResponseAuditInline]

    @admin.display(description="Messages")
    def messages_pretty(self, obj: AIRequestAudit) -> str:
        return _short_json(obj.messages, max_chars=5000)

    @admin.display(description="Tools")
    def tools_pretty(self, obj: AIRequestAudit) -> str:
        return _short_json(obj.tools)

    @admin.display(description="Response format (adapted)")
    def response_format_adapted_pretty(self, obj: AIRequestAudit) -> str:
        return _short_json(obj.response_format_adapted, max_chars=4000)

    @admin.display(description="Response format (final)")
    def response_format_pretty(self, obj: AIRequestAudit) -> str:
        return _short_json(obj.response_format, max_chars=4000)

    @admin.display(description="Prompt meta")
    def prompt_meta_pretty(self, obj: AIRequestAudit) -> str:
        return _short_json(obj.prompt_meta)


@admin.register(AIResponseAudit)
class AIResponseAuditAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "received_at",
        "status_badge",
        "namespace",
        "name",
        "provider_name",
        "client_name",
        "correlation_id",
        "request_id",
    )
    list_filter = (
        "provider_name",
        "client_name",
        "namespace",
        "name",
        ("received_at", admin.DateFieldListFilter),
        ("error", admin.EmptyFieldListFilter),
    )
    search_fields = (
        "id",
        "correlation_id",
        "namespace",
        "name",
        "provider_name",
        "client_name",
        "request__id",
    )
    date_hierarchy = "received_at"
    ordering = ("-received_at", "-id")
    list_per_page = 50

    readonly_fields = (
        "received_at",
        "correlation_id",
        "namespace",
        "kind",
        "name",
        "provider_name",
        "client_name",
        "simulation_pk",
        "request",
        "outputs_pretty",
        "usage_pretty",
        "provider_meta_pretty",
        "error",
    )

    fields = (
        ("received_at", "request"),
        ("name", "provider_name", "client_name"),
        ("namespace", "kind", "simulation_pk", "correlation_id"),
        "status_badge",
        "outputs_pretty",
        "usage_pretty",
        "provider_meta_pretty",
        "error",
    )

    @admin.display(description="Status")
    def status_badge(self, obj: AIResponseAudit) -> str:
        if obj.error:
            return format_html('<span style="color:#b91c1c;">error</span>')
        return format_html('<span style="color:#065f46;">ok</span>')

    @admin.display(description="Usage")
    def usage_pretty(self, obj: AIResponseAudit) -> str:
        return _short_json(obj.usage)

    @admin.display(description="Outputs")
    def outputs_pretty(self, obj: AIResponseAudit) -> str:
        return _short_json(obj.outputs, max_chars=5000)

    @admin.display(description="Provider meta")
    def provider_meta_pretty(self, obj: AIResponseAudit) -> str:
        return _short_json(obj.provider_meta)

    @admin.display(description="Request ID")
    def request_id(self, obj: AIResponseAudit) -> int | None:
        return obj.request_id


@admin.register(AIOutbox)
class AIOutboxAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "event_type",
        "namespace",
        "provider_name",
        "client_name",
        "correlation_id",
        "dispatched_at",
        "attempts",
        "next_attempt_at",
    )
    list_filter = (
        "event_type",
        ("dispatched_at", admin.EmptyFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "id",
        "correlation_id",
        "namespace",
        "provider_name",
        "client_name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    readonly_fields = (
        "created_at",
        "updated_at",
        "event_type",
        "correlation_id",
        "namespace",
        "provider_name",
        "client_name",
        "payload_pretty",
        "dispatched_at",
        "attempts",
        "next_attempt_at",
        "last_error",
    )
    fields = (
        ("created_at", "updated_at"),
        ("event_type", "namespace", "provider_name", "client_name", "correlation_id"),
        "payload_pretty",
        ("dispatched_at", "attempts", "next_attempt_at"),
        "last_error",
    )
    actions = ("mark_selected_dispatched", "reset_selected_for_retry")

    @admin.display(description="Payload")
    def payload_pretty(self, obj: AIOutbox) -> str:
        return _short_json(obj.payload, max_chars=5000)

    @admin.action(description="Mark as dispatched")
    def mark_selected_dispatched(self, request, queryset):
        updated = queryset.update(dispatched_at=admin.timezone.now())
        self.message_user(request, f"Marked {updated} row(s) as dispatched.")

    @admin.action(description="Reset for retry (clear dispatched, +1 attempts)")
    def reset_selected_for_retry(self, request, queryset):
        for row in queryset:
            row.dispatched_at = None
            row.attempts = (row.attempts or 0) + 1
            row.next_attempt_at = None
            row.last_error = None
            row.save(update_fields=["dispatched_at", "attempts", "next_attempt_at", "last_error", "updated_at"])
        self.message_user(request, f"Reset {queryset.count()} row(s) for retry.")