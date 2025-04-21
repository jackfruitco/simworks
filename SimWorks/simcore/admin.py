from django.contrib import admin
from django.utils.html import format_html

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
    change_form_template = "admin/simulation_change_form.html"

    @admin.display(boolean=True, description="Is Complete?")
    def is_complete_display(self, obj):
        return obj.is_complete

    @admin.display(description="Correct Diagnosis")
    def correct_diagnosis(self, obj):
        if obj.is_in_progress:
            return format_html('<img src="/static/admin/img/icon-in-progress.svg" alt="In Progress">')

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
            return format_html('<img src="/static/admin/img/icon-in-progress.svg" alt="In Progress">')

        val = obj.metadata.filter(key="correct treatment plan").values_list("value", flat=True).first()
        if val == "true":
            return format_html('<img src="/static/admin/img/icon-yes.svg" alt="True">')
        elif val == "false":
            return format_html('<img src="/static/admin/img/icon-no.svg" alt="False">')
        elif val == "partial":
            return format_html('<img src="/static/admin/img/icon-maybe.svg" alt="Maybe">')
        return format_html('<img src="/static/admin/img/icon-unknown.svg" alt="Missing">')

    list_display = ("id", "user", "is_complete_display", "correct_diagnosis", "correct_treatment_plan", "start_timestamp")
    fieldsets = [
        (None, {"fields": ("user", ("start_timestamp", "end_timestamp", "time_limit"), "prompt")}),
        ("SCENARIO ATTRIBUTES", {
            "classes": ("collapse",),
            "fields": (("diagnosis", "chief_complaint"), ("correct_diagnosis","correct_treatment_plan"))
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