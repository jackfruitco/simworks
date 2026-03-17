from django.contrib import admin

from .models import (
    ETCO2,
    SPO2,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    Problem,
    PulseAssessment,
    RespiratoryRate,
    RuntimeEvent,
    ScenarioBrief,
    ScenarioInstruction,
    ScenarioInstructionPermission,
    SimulationNote,
    TrainerCommand,
    TrainerRunSummary,
    TrainerSession,
)

_DOMAIN_LIST_DISPLAY = ("id", "timestamp", "simulation", "source", "is_active")
_DOMAIN_LIST_FILTER = ("source", "is_active")
_DOMAIN_SEARCH = ("simulation__id",)
_DOMAIN_ORDERING = ("-timestamp",)


@admin.register(TrainerSession)
class TrainerSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "simulation",
        "status",
        "run_started_at",
        "run_completed_at",
        "last_ai_tick_at",
    )
    list_filter = ("status",)
    search_fields = ("simulation__id", "simulation__user__email")


@admin.register(TrainerCommand)
class TrainerCommandAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "command_type", "status", "issued_at", "processed_at")
    list_filter = ("command_type", "status")
    search_fields = ("idempotency_key", "session__id")


@admin.register(RuntimeEvent)
class RuntimeEventAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("session__id", "simulation__id")


@admin.register(Injury)
class InjuryAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "injury_location", "injury_kind")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(Illness)
class IllnessAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "name")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "problem_kind", "march_category", "severity")
    list_filter = (*_DOMAIN_LIST_FILTER, "problem_kind")
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "intervention_type", "status")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(SimulationNote)
class SimulationNoteAdmin(admin.ModelAdmin):
    list_display = _DOMAIN_LIST_DISPLAY
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(ScenarioBrief)
class ScenarioBriefAdmin(admin.ModelAdmin):
    list_display = _DOMAIN_LIST_DISPLAY
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(PulseAssessment)
class PulseAssessmentAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "location", "present")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(HeartRate)
class HeartRateAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "min_value", "max_value")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(RespiratoryRate)
class RespiratoryRateAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "min_value", "max_value")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(SPO2)
class SPO2Admin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "min_value", "max_value")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(ETCO2)
class ETCO2Admin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "min_value", "max_value")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(BloodGlucoseLevel)
class BloodGlucoseLevelAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "min_value", "max_value")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


@admin.register(BloodPressure)
class BloodPressureAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "min_value", "max_value")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING


admin.site.register(TrainerRunSummary)
admin.site.register(ScenarioInstruction)
admin.site.register(ScenarioInstructionPermission)
