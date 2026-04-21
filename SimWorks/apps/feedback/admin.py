from django.contrib import admin
from django.utils import timezone

from .models import UserFeedback


@admin.register(UserFeedback)
class UserFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "category",
        "status",
        "severity",
        "user",
        "simulation",
        "source",
        "client_platform",
        "client_version",
        "title_preview",
    )
    list_filter = (
        "status",
        "category",
        "source",
        "severity",
        "client_platform",
        "created_at",
    )
    search_fields = (
        "title",
        "body",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "user",
        "account",
        "simulation",
        "conversation",
        "lab_type",
        "category",
        "source",
        "email",
        "rating",
        "client_platform",
        "client_version",
        "os_version",
        "device_model",
        "request_id",
        "session_identifier",
        "context_json",
        "attachments_json",
        "body",
        "title",
    )
    fieldsets = (
        (
            "Submission",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "user",
                    "account",
                    "simulation",
                    "conversation",
                    "lab_type",
                    "category",
                    "source",
                )
            },
        ),
        (
            "Content",
            {"fields": ("title", "body", "rating", "allow_follow_up", "email")},
        ),
        (
            "Triage",
            {"fields": ("status", "severity", "internal_notes", "resolved_at", "resolved_by")},
        ),
        (
            "Client Metadata",
            {
                "fields": (
                    "client_platform",
                    "client_version",
                    "os_version",
                    "device_model",
                    "request_id",
                    "session_identifier",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Payload",
            {"fields": ("context_json", "attachments_json"), "classes": ("collapse",)},
        ),
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Title / Preview")
    def title_preview(self, obj):
        return obj.title or obj.body[:60]

    def save_model(self, request, obj, form, change):
        if change and "status" in form.changed_data and obj.status == UserFeedback.Status.RESOLVED:
            if not obj.resolved_at:
                obj.resolved_at = timezone.now()
            if not obj.resolved_by_id:
                obj.resolved_by = request.user
        super().save_model(request, obj, form, change)
