from typing import ClassVar

from django.contrib import admin
from django.utils.html import format_html

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

    @admin.display(description="Correct Diagnosis")
    def correct_diagnosis(self, obj):
        if obj.is_in_progress:
            return format_html(
                '<img src="/static/admin/img/icon-in-progress.svg" alt="In Progress">'
            )

        val = obj.metadata.filter(key="correct diagnosis").values_list("value", flat=True).first()
        if val == "true":
            return format_html('<img src="/static/admin/img/icon-yes.svg" alt="True">')
        elif val == "false":
            return format_html('<img src="/static/admin/img/icon-no.svg" alt="False">')
        elif val == "partial":
            return format_html('<img src="/static/admin/img/icon-maybe.svg" alt="Maybe">')
        return format_html('<img src="/static/admin/img/icon-unknown.svg" alt="Missing">')

    @admin.display(description="Correct Treatment Plan")
    def correct_treatment_plan(self, obj):
        if obj.is_in_progress:
            return format_html(
                '<img src="/static/admin/img/icon-in-progress.svg" alt="In Progress">'
            )

        val = (
            obj.metadata.filter(key="correct treatment plan")
            .values_list("value", flat=True)
            .first()
        )
        if val == "true":
            return format_html('<img src="/static/admin/img/icon-yes.svg" alt="True">')
        elif val == "false":
            return format_html('<img src="/static/admin/img/icon-no.svg" alt="False">')
        elif val == "partial":
            return format_html('<img src="/static/admin/img/icon-maybe.svg" alt="Maybe">')
        return format_html('<img src="/static/admin/img/icon-unknown.svg" alt="Missing">')

    list_display = (
        "id",
        "user",
        "is_complete_display",
        "correct_diagnosis",
        "correct_treatment_plan",
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
                "fields": (
                    ("diagnosis", "chief_complaint"),
                    ("correct_diagnosis", "correct_treatment_plan"),
                ),
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
