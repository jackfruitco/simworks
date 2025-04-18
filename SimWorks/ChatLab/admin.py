from django.contrib import admin

from .models import *


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "simulation",
        "sender",
        "role",
    )
    list_filter = ("simulation", "role", "sender")

    fieldsets = [
        (None, {"fields": ("simulation", "order", "sender", "role")}),
        ("Contents", {"fields": ("content",)}),
        ("OpenAI Response", {
            "classes": ("collapse",),
            "fields": ("response__raw",)
        })

    ]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_by_display",
        "created_at",
        "modified_by_display",
        "is_archived",
    )
    list_editable = ("is_archived",)
    list_filter = ("created_by", "is_archived")
    search_fields = ("title", "content")

    def created_by_display(self, obj):
        return obj.created_by.username if obj.created_by else "System"

    created_by_display.short_description = "Created By"

    def modified_by_display(self, obj):
        return obj.modified_by.username if obj.modified_by else "System"

    modified_by_display.short_description = "Modified By"


class MetadataInline(admin.TabularInline):
    model = SimulationMetadata
    extra = 0
    fieldsets = [
        (None, {"fields": ("attribute", "key", "value",)}),
    ]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    list_display = ("id", "start_timestamp", "user", "is_complete", "is_timed_out")
    fields = ("user", "start_timestamp", "end_timestamp", "time_limit", "prompt")
    readonly_fields = ("start_timestamp", "end_timestamp")
    list_filter = ("prompt", "end_timestamp", "time_limit")
    search_fields = ("user__username", "prompt__title")
    ordering = ("-id",)

    inlines = [MetadataInline]

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(SimulationMetadata)
class SimulationMetadataAdmin(admin.ModelAdmin):

    def has_change_permission(self, request, obj=None):
        return False