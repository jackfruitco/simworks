from django.contrib import admin
from django.utils.translation import gettext_lazy as _
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
    ScenarioBrief,
    ScenarioInstruction,
    ScenarioInstructionPermission,
    SimulationNote,
    TrainerCommand,
    TrainerRunSummary,
    TrainerRuntimeEvent,
    TrainerSession,
    VitalMeasurement,
)


class VitalAbbreviatedNameFilter(admin.SimpleListFilter):
    title = _("vital")
    parameter_name = "vital_abbrev"

    def lookups(self, request, model_admin):
        return (
            ("HR", "HR"),
            ("RR", "RR"),
            ("SPO2", "SPO2"),
            ("ETCO2", "ETCO2"),
            ("BGL", "BGL"),
            ("BP", "BP"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "HR":
            return queryset.instance_of(HeartRate)
        if value == "RR":
            return queryset.instance_of(RespiratoryRate)
        if value == "SPO2":
            return queryset.instance_of(SPO2)
        if value == "ETCO2":
            return queryset.instance_of(ETCO2)
        if value == "BGL":
            return queryset.instance_of(BloodGlucoseLevel)
        if value == "BP":
            return queryset.instance_of(BloodPressure)
        return queryset


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
        SimulationNote,
        ScenarioBrief,
        VitalMeasurement,
        HeartRate,
        RespiratoryRate,
        SPO2,
        ETCO2,
        BloodGlucoseLevel,
        BloodPressure,
    )
    list_display = (
        "id",
        "timestamp",
        "simulation",
        "source",
        "vital_abbreviated_name",
        "is_active",
    )
    list_filter = ("source", VitalAbbreviatedNameFilter, "is_active")
    search_fields = ("simulation__id",)
    ordering = ("-timestamp",)

    @admin.display(description="Vital")
    def vital_abbreviated_name(self, obj):
        if isinstance(obj, VitalMeasurement):
            return obj.abbreviated_name
        return ""


class ABCEventChildAdmin(PolymorphicChildModelAdmin):
    base_model = ABCEvent
    list_display = (
        "id",
        "timestamp",
        "simulation",
        "source",
        "vital_abbreviated_name",
        "is_active",
    )
    list_filter = ("source", VitalAbbreviatedNameFilter, "is_active")
    search_fields = ("simulation__id",)
    ordering = ("-timestamp",)

    @admin.display(description="Vital")
    def vital_abbreviated_name(self, obj):
        if isinstance(obj, VitalMeasurement):
            return obj.abbreviated_name
        return ""


@admin.register(Injury)
class InjuryAdmin(ABCEventChildAdmin):
    base_model = Injury


@admin.register(Illness)
class IllnessAdmin(ABCEventChildAdmin):
    base_model = Illness


@admin.register(Intervention)
class InterventionAdmin(ABCEventChildAdmin):
    base_model = Intervention


@admin.register(SimulationNote)
class SimulationNoteAdmin(ABCEventChildAdmin):
    base_model = SimulationNote


@admin.register(ScenarioBrief)
class ScenarioBriefAdmin(ABCEventChildAdmin):
    base_model = ScenarioBrief


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
