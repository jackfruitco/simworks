



import json
from typing import Any

from django.contrib import admin
from django.utils import timezone as tz_
from django.utils.html import format_html

from .models import AIOutbox


# ----------------------------- helpers ---------------------------------

def _short_json(value: Any, max_chars: int = 160) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(value)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


# ----------------------------- ModelAdmins ------------------------------
# Note: AIRequestAudit and AIResponseAudit admin classes removed.
# ServiceCallRecord provides sufficient tracking.


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
        ("dispatched_at", "attempts", "next_attempt_at"),
        "last_error",
    )
    actions = ("mark_selected_dispatched", "reset_selected_for_retry")

    @admin.display(description="Payload")
    def payload_pretty(self, obj: AIOutbox) -> str:
        return _short_json(obj.payload, max_chars=5000)

    @admin.action(description="Mark as dispatched")
    def mark_selected_dispatched(self, request, queryset):
        updated = queryset.update(dispatched_at=tz_.now())
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