from django.contrib import admin
from polymorphic.admin import (
    PolymorphicChildModelAdmin,
    PolymorphicParentModelAdmin,
)

from .models import (
    ETCO2,
    SPO2,
    ABCEvent,
    BloodGlucoseLevel,
    BloodPressure,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    RespiratoryRate,
    ScenarioInstruction,
    ScenarioInstructionPermission,
    TrainerCommand,
    TrainerRunSummary,
    TrainerRuntimeEvent,
    TrainerSession,
    VitalMeasurement,
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


@admin.register(ABCEvent)
class ABCEventAdmin(PolymorphicParentModelAdmin):
    base_model = ABCEvent
    child_models = (
        Injury,
        Illness,
        Intervention,
        VitalMeasurement,
        HeartRate,
        RespiratoryRate,
        SPO2,
        ETCO2,
        BloodGlucoseLevel,
        BloodPressure,
    )
    list_display = ("id", "timestamp", "simulation", "source", "is_active")
    list_filter = ("source", "is_active")
    search_fields = ("simulation__id",)
    ordering = ("-timestamp",)


class ABCEventChildAdmin(PolymorphicChildModelAdmin):
    base_model = ABCEvent
    list_display = ("id", "timestamp", "simulation", "source", "is_active")
    list_filter = ("source", "is_active")
    search_fields = ("simulation__id",)
    ordering = ("-timestamp",)


@admin.register(Injury)
class InjuryAdmin(ABCEventChildAdmin):
    base_model = Injury


@admin.register(Illness)
class IllnessAdmin(ABCEventChildAdmin):
    base_model = Illness


@admin.register(Intervention)
class InterventionAdmin(ABCEventChildAdmin):
    base_model = Intervention


@admin.register(VitalMeasurement)
class VitalMeasurementAdmin(ABCEventChildAdmin):
    base_model = VitalMeasurement


@admin.register(HeartRate)
class HeartRateAdmin(ABCEventChildAdmin):
    base_model = HeartRate


@admin.register(RespiratoryRate)
class RespiratoryRateAdmin(ABCEventChildAdmin):
    base_model = RespiratoryRate


@admin.register(SPO2)
class SPO2Admin(ABCEventChildAdmin):
    base_model = SPO2


@admin.register(ETCO2)
class ETCO2Admin(ABCEventChildAdmin):
    base_model = ETCO2


@admin.register(BloodGlucoseLevel)
class BloodGlucoseLevelAdmin(ABCEventChildAdmin):
    base_model = BloodGlucoseLevel


@admin.register(BloodPressure)
class BloodPressureAdmin(ABCEventChildAdmin):
    base_model = BloodPressure


admin.site.register(TrainerRunSummary)
admin.site.register(ScenarioInstruction)
admin.site.register(ScenarioInstructionPermission)
