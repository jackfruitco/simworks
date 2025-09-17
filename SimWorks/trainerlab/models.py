import warnings

from django.db import models
from polymorphic.models import PolymorphicModel
from django.utils.translation import gettext_lazy as _

from simcore.models import BaseSession


class TrainerSession(BaseSession):
    """
    Represents a session within TrainerLab that extends a shared Simulation instance.
    Additional training-specific behaviors or fields can be added here.
    """

    pass

# class EventType(models.Model):
#
#     name = models.CharField(max_length=100, unique=True)
#     description = models.TextField(blank=True)
#
#     def __str__(self):
#         return self.name


class ABCEvent(PolymorphicModel):
    """Abstract class for Events"""
    timestamp = models.DateTimeField(auto_now_add=True)

    warnings.warn("`ABCEvent.event_type` is deprecated. Use `ABCEvent.polymorphic_ctype` instead.", DeprecationWarning, stacklevel=2)
    # event_type = models.ForeignKey(EventType, on_delete=models.CASCADE, related_name="events")
    simulation = models.ForeignKey("simcore.Simulation", on_delete=models.CASCADE, related_name="events")

    def __str__(self):
        return f"{self.__class__.__name__} at {self.timestamp:%H:%M:%S}"


class Injury(ABCEvent):
    class InjuryCategory(models.TextChoices):
        M = "M", _("Massive Hemorrhage")
        A = "A", _("Airway")
        R = "R", _("Respiration")
        C = "C", _("Circulatory")
        H1 = "H1", _("Hypothermia")
        H2 = "H2", _("Head Injury")
        PFC = "PC", _("Prolonged Field Care")


    class InjuryLocation(models.TextChoices):
        HEAD_LEFT_ANTERIOR = "HLA", _("Left Anterior Head")
        HEAD_RIGHT_ANTERIOR = "HRA", _("Right Anterior Head")
        HEAD_LEFT_POSTERIOR = "HLP", _("Left Posterior Head")
        HEAD_RIGHT_POSTERIOR = "HRP", _("Right Posterior Head")

        NECK_LEFT_ANTERIOR = "NLA", _("Left Anterior Neck")
        NECK_RIGHT_ANTERIOR = "NRA", _("Right Anterior Neck")
        NECK_LEFT_POSTERIOR = "NLP", _("Left Posterior Neck")
        NECK_RIGHT_POSTERIOR = "NRP", _("Right Posterior Neck")

        ARM_LEFT_UPPER = "LUA", _("Left Upper Arm")
        ARM_LEFT_LOWER = "LLA", _("Left Lower Arm")
        ARM_RIGHT_UPPER = "RUA", _("Right Upper Arm")
        ARM_RIGHT_LOWER = "RLA", _("Right Lower Arm")

        THORAX_LEFT_ANTERIOR = "TLA", _("Left Anterior Chest")
        THORAX_RIGHT_ANTERIOR = "TRA", _("Right Anterior Chest")
        THORAX_LEFT_POSTERIOR = "TLP", _("Left Posterior Chest")
        THORAX_RIGHT_POSTERIOR = "TRP", _("Right Posterior Chest")

        ABDOMEN_LEFT_ANTERIOR = "ALA", _("Left Anterior Abdomen")
        ABDOMEN_RIGHT_ANTERIOR = "ARA", _("Right Anterior Abdomen")
        ABDOMEN_LEFT_POSTERIOR = "ALP", _("Left Posterior Abdomen")
        ABDOMEN_RIGHT_POSTERIOR = "ARP", _("Right Posterior Abdomen")

        LEG_LEFT_UPPER = "LUL", _("Left Upper Leg")
        LEG_LEFT_LOWER = "LLL", _("Left Lower Leg")
        LEG_RIGHT_UPPER = "RUL", _("Right Upper Leg")
        LEG_RIGHT_LOWER = "RLL", _("Right Lower Leg")

        JUNCTIONAL_LEFT_AXILLARY = "JLX", _("Left Junctional Axilla")
        JUNCTIONAL_RIGHT_AXILLARY = "JRX", _("Right Junctional Axilla")
        JUNCTIONAL_LEFT_INGUINAL = "JLI", _("Left Junctional Inguinal")
        JUNCTIONAL_RIGHT_INGUINAL = "JRI", _("Right Junctional Inguinal")
        JUNCTIONAL_LEFT_NECK = "JLN", _("Left Junctional Neck")
        JUNCTIONAL_RIGHT_NECK = "JRN", _("Right Junctional Neck")


    class InjuryKind(models.TextChoices):
        AMPUTATION = "AMP", _("Amputation")
        AMPUTATION_PARTIAL = "PAMP", _("Partial Amputation")
        LACERATION = "LAC", _("Laceration")
        LACERATION_INTERNAL = "LIC", _("Internal Laceration")
        BURN = "BURN", _("Burn")
        PUNCTURE = "PUN", _("Puncture")
        PENETRATION = "PEN", _("Penetration")
        GSW = "GSW", _("Gunshot Wound")
        SHRAPNEL = "SHR", _("Shrapnel")

    injury_category = models.CharField(
        max_length=2,
        choices=InjuryCategory.choices,     # type: ignore[attr-defined]
        db_index=True,
        help_text="The category of the injury"
    )
    injury_location = models.CharField(
        max_length=4,
        choices=InjuryLocation.choices,     # type: ignore[attr-defined]
        db_index=True,
        help_text="The location of the injury"
    )
    injury_kind = models.CharField(
        max_length=4,
        choices=InjuryKind.choices,         # type: ignore[attr-defined]
        db_index=True,
        help_text="The kind of injury"
    )

    injury_description = models.CharField(max_length=100)

    parent_injury = models.ForeignKey("self", on_delete=models.CASCADE, related_name="children_injuries", null=True, blank=True)
    is_treated = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)

    @property
    def original_injury(self):
        return self.parent_injury or self

    @property
    def is_parent_injury(self):
        return self.parent_injury is None

    @property
    def is_child_injury(self):
        return self.parent_injury is not None

    def __str__(self):
        return (
            f"{self.get_injury_kind_display()} at "
            f"{self.get_injury_location_display()} "
            f"({self.get_injury_category_display()})"
        )

class Intervention(ABCEvent):
    class InterventionGroups:
        class TOURNIQUET(models.TextChoices):
            HASTY = "M-TQ-H", _("Hasty Tourniquet")
            DELIBERATE = "M-TQ-D", _("Deliberate Tourniquet")


        class GAUZE(models.TextChoices):
            PACKED = "M-GZ-PK", _("Non-Hemostatic Gauze Packed")
            PACKED_HEMOSTATIC = "M-GZ-PK-H", _("Hemostatic Gauze Packed")
            WRAPPED = "M-GZ-WP", _("Non-Hemostatic Gauze Wrapped")
            WRAPPED_HEMOSTATIC = "M-GZ-WP-H", _("Hemostatic Gauze Wrapped")
            ZFOLDED = "M-GZ-ZF", _("Z-Folded Gauze")
            ZFOLDED_HEMOSTATIC = "M-GZ-ZF-H", _("Hemostatic Z-Folded Gauze")


        class AIRWAY(models.TextChoices):
            POSITION_RECOVERY = "A-P-R", _("Recovery Position")
            POSITION_OF_COMFORT = "A-P-C", _("Position of Comfort")
            POSITION_OTHER = "A-P-O", _("Other Position")
            HEAD_TILT_CHIN_LIFT = "A-HTCL", _("Head-Tilt-Chin-Lift")
            JAW_THRUST = "A-JT", _("Jaw-Thrust")
            NPA = "A-NPA", _("NPA")
            OPA = "A-OPA", _("OPA")
            SGA = "A-SGA", _("SGA")
            INTUBATION = "A-INT", _("Intubation")
            SURGICAL_OPEN = "A-SURG-O", _("Surgical Airway (Open Technique)")
            SURGICAL_BOUGIE = "A-SURG-B", _("Surgical Airway (Bougie-aided)")


class VitalMeasurement(ABCEvent):
    """
    Abstract class for vital signs.

    To reduce LLM AI calls, we use a range of values for each vital sign,
    and the front end will use the min and max values to generate a random value.
    """
    min_value = models.PositiveSmallIntegerField(
        help_text="Minimum value for range of this vital sign"
    )
    max_value = models.PositiveSmallIntegerField(
        help_text="Maximum value for range of this vital sign"
    )

    lock_value = models.BooleanField(
        default=False,
        help_text=(
            "Lock the value to the minimum (instead of a range between "
            "min and max)"
        ),
    )

    @property
    def unit(self):
        raise NotImplementedError("Subclasses must implement unit()")

    @property
    def friendly_name(self):
        raise NotImplementedError("Subclasses must implement friendly_name()")

    @property
    def abbreviated_name(self):
        raise NotImplementedError("Subclasses must implement abbreviated_name()")

    def __str__(self):
        return (
            f"{self.__class__.__name__} {self.timestamp:%H:%M:%S} "
            f"{self.min_value}-{self.max_value}{self.unit}"
        )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(min_value__lte=models.F("max_value")),
                name="vital_min_le_max",
            ),
        ]


class HeartRate(VitalMeasurement):
    @property
    def unit(self):
        return "bpm"

    @property
    def friendly_name(self):
        return "Heart Rate"

    @property
    def abbreviated_name(self):
        return "HR"


class SPO2(VitalMeasurement):
    @property
    def unit(self):
        return "%"

    @property
    def friendly_name(self):
        return "Peripheral Oxygen Saturation"

    @property
    def abbreviated_name(self):
        return self.__class__.__name__


class ETCO2(VitalMeasurement):
    @property
    def unit(self):
        return "mmHg"

    @property
    def friendly_name(self):
        return "End Tidal CO2"

    @property
    def abbreviated_name(self):
        return self.__class__.__name__


class BloodGlucoseLevel(VitalMeasurement):
    @property
    def unit(self):
        return "mg/dL"

    @property
    def friendly_name(self):
        return self.__class__.__name__

    @property
    def abbreviated_name(self):
        return "BGL"


class BloodPressure(VitalMeasurement):
    min_value_diastolic = models.PositiveSmallIntegerField()
    max_value_diastolic = models.PositiveSmallIntegerField()

    # min_value and max_value are used for systolic pressures but aliased for convenience
    @property
    def min_value_systolic(self):
        return self.min_value

    @property
    def max_value_systolic(self):
        return self.max_value

    @property
    def unit(self):
        return "mmHg"

    @property
    def friendly_name(self):
        return self.__class__.__name__

    @property
    def abbreviated_name(self):
        return "BP"

    def __str__(self):
        return (
            f"{self.__class__.__name__} "
            f"{self.timestamp:%H:%M:%S} "
            f"{self.min_value}-{self.max_value}/"
            f"{self.min_value_diastolic}-{self.max_value_diastolic} mmHg"
        )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(min_value_diastolic__lte=models.F("max_value_diastolic")),
                name="bp_dia_min_le_max",
            ),
        ]