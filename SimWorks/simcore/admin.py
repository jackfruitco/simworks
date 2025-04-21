from django.contrib import admin

from .models import *

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

    @admin.display(boolean=True, description="Is Complete?")
    def is_complete_display(self, obj):
        return obj.is_complete

    @admin.display(description="Correct Diagnosis")
    def correct_diagnosis(self, obj):
        if obj.is_in_progress: return "still in progress"
        val = obj.metadata.filter(key="correct_diagnosis").values_list("value", flat=True).first()
        return "undetermined" if val is None else val

    @admin.display(description="Correct Treatment Plan")
    def correct_treatment_plan(self, obj):
        if obj.is_in_progress: return "still in progress"
        val= obj.metadata.filter(key="correct_treatment_plan").values_list("value", flat=True).first()
        return "undetermined" if val is None else val

    list_display = ("id", "user", "is_complete_display", "correct_diagnosis", "correct_treatment_plan", "start_timestamp")
    fieldsets = [
        (None, {"fields": ("user", "start_timestamp", "end_timestamp", "time_limit", "prompt")}),
        ("SCENARIO ATTRIBUTES", {
            "classes": ("collapse",),
            "fields": ("diagnosis", "chief_complaint", "correct_diagnosis","correct_treatment_plan")
        }),
    ]
    list_filter = ("user",)
    search_fields = ("user__username", "prompt__title", "diagnosis", "chief_complaint")
    ordering = ("-id",)

    inlines = [MetadataInline]

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(SimulationMetadata)
class SimulationMetadataAdmin(admin.ModelAdmin):

    def has_change_permission(self, request, obj=None):
        return False