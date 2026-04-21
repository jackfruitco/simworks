from django.contrib import admin

from .models import FeedbackAuditEvent, FeedbackRemark, UserFeedback


class FeedbackRemarkInline(admin.TabularInline):
    model = FeedbackRemark
    extra = 0
    can_delete = False
    fields = ("created_at", "author", "body")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class FeedbackAuditEventInline(admin.TabularInline):
    model = FeedbackAuditEvent
    extra = 0
    can_delete = False
    fields = ("created_at", "actor", "event_type", "metadata_json")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UserFeedback)
class UserFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "category",
        "status",
        "is_reviewed",
        "is_archived",
        "user",
        "simulation",
        "source",
        "client_platform",
        "client_version",
        "title_preview",
    )
    list_filter = (
        "status",
        "is_reviewed",
        "is_archived",
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
        "allow_follow_up",
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
        "is_reviewed",
        "reviewed_at",
        "resolved_at",
        "reviewed_by",
        "is_archived",
        "archived_at",
        "archived_by",
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
            "Workflow",
            {
                "fields": (
                    "status",
                    "severity",
                    "is_reviewed",
                    "reviewed_at",
                    "resolved_at",
                    "reviewed_by",
                    "is_archived",
                    "archived_at",
                    "archived_by",
                )
            },
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
    inlines = (FeedbackRemarkInline, FeedbackAuditEventInline)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Title / Preview")
    def title_preview(self, obj):
        return obj.title or obj.body[:60]


@admin.register(FeedbackRemark)
class FeedbackRemarkAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "author", "body_preview")
    list_filter = ("created_at",)
    search_fields = ("body", "author__email", "feedback__title", "feedback__body")
    readonly_fields = ("feedback", "author", "body", "created_at")
    date_hierarchy = "created_at"

    @admin.display(description="Body")
    def body_preview(self, obj):
        return obj.body[:80]


@admin.register(FeedbackAuditEvent)
class FeedbackAuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feedback", "event_type", "actor")
    list_filter = ("event_type", "created_at")
    search_fields = ("feedback__title", "feedback__body", "actor__email")
    readonly_fields = ("feedback", "actor", "event_type", "created_at", "metadata_json")
    date_hierarchy = "created_at"
