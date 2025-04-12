from django.contrib import admin

from .models import *

# Register your models here.
admin.site.register(Message)
admin.site.register(SimulationMetadata)


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
    readonly_fields = ("attribute", "key")
    fieldsets = [
        (None, {"fields": ("value",)}),
    ]


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    list_display = ("id", "start", "user", "is_complete", "is_timed_out")
    fields = ("user", "start", "end", "time_limit", "prompt")
    readonly_fields = ("start", "end")
    list_filter = ("prompt", "end", "time_limit")
    search_fields = ("user__username", "prompt__title")
    ordering = ("-id",)

    inlines = [MetadataInline]
