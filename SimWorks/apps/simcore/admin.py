from typing import ClassVar

from django.contrib import admin

from apps.chatlab.models import Message, MessageMediaLink

from .models import (
    Conversation,
    ConversationType,
    ModifierCatalog,
    ModifierDefinition,
    ModifierGroup,
    Simulation,
    SimulationImage,
    SimulationMetadata,
)


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


class ModifierDefinitionInline(admin.TabularInline):
    model = ModifierDefinition
    extra = 0
    fields = (
        "key",
        "label",
        "description",
        "prompt_fragment",
        "sort_order",
        "is_active",
        "manually_edited",
    )


class ModifierGroupInline(admin.TabularInline):
    model = ModifierGroup
    extra = 0
    fields = (
        "key",
        "label",
        "description",
        "selection_mode",
        "required",
        "sort_order",
        "is_active",
    )


@admin.register(ModifierCatalog)
class ModifierCatalogAdmin(admin.ModelAdmin):
    list_display = ("lab_type", "version", "source", "is_active", "modified_at")
    list_filter = ("is_active", "lab_type")
    inlines: ClassVar[list] = [ModifierGroupInline]


@admin.register(ModifierGroup)
class ModifierGroupAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "label",
        "catalog",
        "selection_mode",
        "required",
        "sort_order",
        "is_active",
    )
    list_filter = ("catalog__lab_type", "is_active", "selection_mode")
    search_fields = ("key", "label")
    ordering = ("catalog__lab_type", "sort_order", "key")
    inlines: ClassVar[list] = [ModifierDefinitionInline]


@admin.register(ModifierDefinition)
class ModifierDefinitionAdmin(admin.ModelAdmin):
    list_display = ("key", "label", "group", "sort_order", "is_active", "manually_edited")
    list_filter = ("group__catalog__lab_type", "is_active", "manually_edited")
    search_fields = ("key", "label", "description", "prompt_fragment")
    ordering = ("group__catalog__lab_type", "group__sort_order", "sort_order", "key")


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
