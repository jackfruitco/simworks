from django.contrib import admin

from .models import (
    ETCO2,
    SPO2,
    AssessmentFinding,
    BloodGlucoseLevel,
    BloodPressure,
    DiagnosticResult,
    DispositionState,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    Problem,
    PulseAssessment,
    RecommendationEvaluation,
    RecommendedIntervention,
    ResourceState,
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
    list_display = (*_DOMAIN_LIST_DISPLAY, "title", "injury_location", "injury_kind")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation",)
    readonly_fields = ("kind", "code", "slug")


@admin.register(Illness)
class IllnessAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "name", "code")
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = _DOMAIN_SEARCH
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation",)
    readonly_fields = ("kind", "code", "slug")


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = (
        *_DOMAIN_LIST_DISPLAY,
        "display_name",
        "kind",
        "status",
        "march_category",
        "severity",
        "cause_kind",
        "cause_id",
        "parent_problem",
    )
    list_filter = (*_DOMAIN_LIST_FILTER, "status", "kind")
    search_fields = (*_DOMAIN_SEARCH, "display_name", "kind", "code")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation", "cause_injury", "cause_illness", "parent_problem")
    autocomplete_fields = ("parent_problem", "triggering_intervention")


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = (
        *_DOMAIN_LIST_DISPLAY,
        "intervention_type",
        "status",
        "effectiveness",
        "initiated_by_type",
        "target_problem",
        "adjudication_rule_id",
    )
    list_filter = _DOMAIN_LIST_FILTER
    search_fields = (*_DOMAIN_SEARCH, "intervention_type", "target_problem__display_name")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation", "target_problem")


@admin.register(RecommendedIntervention)
class RecommendedInterventionAdmin(admin.ModelAdmin):
    list_display = (
        *_DOMAIN_LIST_DISPLAY,
        "title",
        "validation_status",
        "recommendation_source",
        "target_problem",
    )
    list_filter = (*_DOMAIN_LIST_FILTER, "validation_status", "recommendation_source")
    search_fields = (*_DOMAIN_SEARCH, "title", "kind", "code", "target_problem__display_name")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation", "target_problem")


@admin.register(AssessmentFinding)
class AssessmentFindingAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "title", "status", "severity", "target_problem")
    list_filter = (*_DOMAIN_LIST_FILTER, "status", "severity", "kind")
    search_fields = (*_DOMAIN_SEARCH, "title", "kind", "target_problem__display_name")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation", "target_problem")


@admin.register(DiagnosticResult)
class DiagnosticResultAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "title", "status", "target_problem", "value_text")
    list_filter = (*_DOMAIN_LIST_FILTER, "status", "kind")
    search_fields = (*_DOMAIN_SEARCH, "title", "kind", "target_problem__display_name")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation", "target_problem")


@admin.register(ResourceState)
class ResourceStateAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "title", "status", "quantity_available", "quantity_unit")
    list_filter = (*_DOMAIN_LIST_FILTER, "status", "kind")
    search_fields = (*_DOMAIN_SEARCH, "title", "kind", "code")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation",)


@admin.register(DispositionState)
class DispositionStateAdmin(admin.ModelAdmin):
    list_display = (*_DOMAIN_LIST_DISPLAY, "status", "transport_mode", "destination", "eta_minutes")
    list_filter = (*_DOMAIN_LIST_FILTER, "status")
    search_fields = (*_DOMAIN_SEARCH, "destination", "transport_mode")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation",)


@admin.register(RecommendationEvaluation)
class RecommendationEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        *_DOMAIN_LIST_DISPLAY,
        "title",
        "validation_status",
        "recommendation_source",
        "target_problem",
        "rejection_reason",
    )
    list_filter = (*_DOMAIN_LIST_FILTER, "validation_status", "recommendation_source")
    search_fields = (*_DOMAIN_SEARCH, "title", "raw_kind", "normalized_kind")
    ordering = _DOMAIN_ORDERING
    list_select_related = ("simulation", "target_problem", "recommendation")


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
