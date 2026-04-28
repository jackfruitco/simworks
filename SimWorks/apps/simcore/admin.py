from typing import ClassVar

from django.contrib import admin

from apps.chatlab.models import Message, MessageMediaLink

from .models import Conversation, ConversationType, Simulation, SimulationImage, SimulationMetadata


class MetadataInline(admin.TabularInline):
    model = SimulationMetadata
    extra = 0
    fieldsets: ClassVar[tuple[tuple[str | None, dict[str, tuple[str, ...]]], ...]] = (
        (
            None,
            {
                "fields": (
                    "key",
                    "value",
                )
            },
        ),
    )

    def has_change_permission(self, request, obj=None):
        return False


class MediaMessageInLine(admin.TabularInline):
    model = MessageMediaLink
    fk_name = "media"
    extra = 0

    def has_change_permission(self, request, obj=None):
        return False


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fieldsets: ClassVar[tuple[tuple[str | None, dict[str, tuple[str, ...]]], ...]] = (
        (None, {"fields": ("sender", "role", "content")}),
    )


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    change_form_template = "admin/simulation_change_form.html"

    @admin.display(boolean=True, description="Is Complete?")
    def is_complete_display(self, obj):
        return obj.is_complete

    list_display = (
        "id",
        "user",
        "is_complete_display",
        "start_timestamp",
    )
    fieldsets: ClassVar[tuple[tuple[str | None, dict[str, object]], ...]] = (
        (
            None,
            {
                "fields": (
                    "user",
                    ("start_timestamp", "end_timestamp", "time_limit"),
                    "prompt",
                )
            },
        ),
        (
            "SCENARIO ATTRIBUTES",
            {
                "classes": ("collapse",),
                "fields": (("diagnosis", "chief_complaint"),),
            },
        ),
    )
    list_filter = ("user",)
    search_fields = ("user__username", "diagnosis", "chief_complaint")
    ordering = ("-id",)

    inlines: ClassVar[tuple[type[admin.TabularInline], ...]] = (MetadataInline,)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SimulationMetadata)
class SimulationMetadataAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SimulationImage)
class SimulationImageAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ConversationType)
class ConversationTypeAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "display_name",
        "ai_persona",
        "locks_with_simulation",
        "is_active",
        "sort_order",
    )
    list_filter = ("locks_with_simulation", "is_active")
    search_fields = ("slug", "display_name")
    ordering = ("sort_order",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "simulation",
        "conversation_type",
        "display_name",
        "is_archived",
        "created_at",
    )
    list_filter = ("conversation_type", "is_archived")
    search_fields = ("display_name", "simulation__id")
    raw_id_fields = ("simulation",)
    ordering = ("-created_at",)
