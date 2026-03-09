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
    ScenarioInstruction,
    ScenarioInstructionPermission,
    TrainerCommand,
    TrainerRunSummary,
    TrainerRuntimeEvent,
    TrainerSession,
)


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


@admin.register(TrainerRuntimeEvent)
class TrainerRuntimeEventAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("session__id", "simulation__id")


admin.site.register(TrainerRunSummary)
admin.site.register(Injury)
admin.site.register(Illness)
admin.site.register(Intervention)
admin.site.register(HeartRate)
admin.site.register(SPO2)
admin.site.register(ETCO2)
admin.site.register(BloodGlucoseLevel)
admin.site.register(BloodPressure)
admin.site.register(ScenarioInstruction)
admin.site.register(ScenarioInstructionPermission)
