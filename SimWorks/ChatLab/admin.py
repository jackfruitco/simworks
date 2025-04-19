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