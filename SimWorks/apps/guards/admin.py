from django.contrib import admin

from .models import SessionPresence, UsageRecord


@admin.register(SessionPresence)
class SessionPresenceAdmin(admin.ModelAdmin):
    list_display = (
        "simulation_id",
        "lab_type",
        "guard_state",
        "engine_runnable",
        "last_presence_at",
        "paused_at",
    )
    list_filter = ("lab_type", "guard_state", "engine_runnable")
    readonly_fields = ("created_at", "modified_at")


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = (
        "scope_type",
        "lab_type",
        "product_code",
        "total_tokens",
        "service_call_count",
        "period_start",
    )
    list_filter = ("scope_type", "lab_type")
    readonly_fields = ("created_at", "modified_at")
