from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from polymorphic.models import PolymorphicModel

from apps.simcore.models import BaseSession


class SessionStatus(models.TextChoices):
    SEEDED = "seeded", _("Seeded")
    RUNNING = "running", _("Running")
    PAUSED = "paused", _("Paused")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class EventSource(models.TextChoices):
    AI = "ai", _("AI")
    INSTRUCTOR = "instructor", _("Instructor")
    SYSTEM = "system", _("System")


class TrainerSession(BaseSession):
    """TrainerLab runtime session attached to a Simulation."""

    status = models.CharField(
        max_length=16, choices=SessionStatus.choices, default=SessionStatus.SEEDED
    )
    scenario_spec_json = models.JSONField(default=dict, blank=True)
    runtime_state_json = models.JSONField(default=dict, blank=True)
    initial_directives = models.TextField(blank=True, default="")
    tick_interval_seconds = models.PositiveSmallIntegerField(default=15)
    tick_nonce = models.PositiveIntegerField(default=0)

    run_started_at = models.DateTimeField(blank=True, null=True)
    run_paused_at = models.DateTimeField(blank=True, null=True)
    run_completed_at = models.DateTimeField(blank=True, null=True)
    last_ai_tick_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="idx_trainer_session_status"),
            models.Index(fields=["run_started_at"], name="idx_trainer_session_started"),
        ]


class TrainerCommand(models.Model):
    """Audit-safe command log for all mutable TrainerLab actions."""

    class CommandType(models.TextChoices):
        CREATE_SESSION = "create_session", _("Create Session")
        START = "start", _("Start")
        PAUSE = "pause", _("Pause")
        RESUME = "resume", _("Resume")
        STOP = "stop", _("Stop")
        STEER_PROMPT = "steer_prompt", _("Steer Prompt")
        INJECT_EVENT = "inject_event", _("Inject Event")
        ADJUST_SCENARIO = "adjust_scenario", _("Adjust Scenario")
        APPLY_PRESET = "apply_preset", _("Apply Preset")

    class CommandStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSED = "processed", _("Processed")
        FAILED = "failed", _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        "trainerlab.TrainerSession", on_delete=models.CASCADE, related_name="commands"
    )
    command_type = models.CharField(max_length=32, choices=CommandType.choices)
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=CommandStatus.choices, default=CommandStatus.PENDING
    )

    idempotency_key = models.CharField(max_length=255, unique=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trainerlab_commands",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["session", "issued_at"], name="idx_trainer_cmd_session"),
            models.Index(fields=["status"], name="idx_trainer_cmd_status"),
        ]


class TrainerRuntimeEvent(models.Model):
    """Append-only TrainerLab event stream feeding outbox + SSE."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        "trainerlab.TrainerSession", on_delete=models.CASCADE, related_name="runtime_events"
    )
    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="trainer_runtime_events",
    )
    event_type = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=100, blank=True, null=True)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trainer_runtime_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["simulation", "created_at"], name="idx_trainer_evt_sim"),
            models.Index(fields=["session", "created_at"], name="idx_trainer_evt_session"),
        ]


class TrainerRunSummary(models.Model):
    session = models.OneToOneField(
        "trainerlab.TrainerSession", on_delete=models.CASCADE, related_name="summary"
    )
    summary_json = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)
    generator_version = models.CharField(max_length=32, default="v1")


class ScenarioInstruction(models.Model):
    """Reusable trainer scenario presets with explicit sharing metadata."""

    class Severity(models.TextChoices):
        LOW = "low", _("Low")
        MODERATE = "moderate", _("Moderate")
        HIGH = "high", _("High")
        CRITICAL = "critical", _("Critical")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trainer_scenario_instructions",
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    instruction_text = models.TextField(blank=True, default="")
    injuries_json = models.JSONField(default=list, blank=True)
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.MODERATE,
    )
    metadata_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-modified_at", "-id")
        indexes = [
            models.Index(fields=["owner", "is_active"], name="idx_scenario_owner_active"),
            models.Index(fields=["severity"], name="idx_scenario_severity"),
        ]

    def __str__(self):
        return f"{self.title} ({self.owner_id})"


class ScenarioInstructionPermission(models.Model):
    """Per-user ACL for scenario presets."""

    scenario_instruction = models.ForeignKey(
        "trainerlab.ScenarioInstruction",
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trainer_scenario_instruction_permissions",
    )
    can_read = models.BooleanField(default=True)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_share = models.BooleanField(default=False)
    can_duplicate = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_trainer_scenario_permissions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario_instruction", "user"],
                name="uniq_trainer_scenario_permission",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "can_read"], name="idx_scenario_perm_user_read"),
            models.Index(
                fields=["scenario_instruction", "can_share"],
                name="idx_scenario_perm_share",
            ),
        ]

    def __str__(self):
        return f"{self.scenario_instruction_id}:{self.user_id}"


class ABCEvent(PolymorphicModel):
    """Abstract class for mutable TrainerLab domain events."""

    timestamp = models.DateTimeField(auto_now_add=True)
    simulation = models.ForeignKey(
        "simcore.Simulation", on_delete=models.CASCADE, related_name="events"
    )
    source = models.CharField(
        max_length=16, choices=EventSource.choices, default=EventSource.SYSTEM
    )
    supersedes_event = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_domain_events",
    )
    is_active = models.BooleanField(default=True)

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
        ARM_LEFT_HAND = "LHA", _("Left Hand")
        ARM_RIGHT_UPPER = "RUA", _("Right Upper Arm")
        ARM_RIGHT_LOWER = "RLA", _("Right Lower Arm")
        ARM_RIGHT_HAND = "RHA", _("Right Hand")

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
        LEG_LEFT_FOOT = "LFT", _("Left Foot")
        LEG_RIGHT_UPPER = "RUL", _("Right Upper Leg")
        LEG_RIGHT_LOWER = "RLL", _("Right Lower Leg")
        LEG_RIGHT_FOOT = "RFT", _("Right Foot")

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
        choices=InjuryCategory.choices,
        db_index=True,
        help_text="The category of the injury",
    )
    injury_location = models.CharField(
        max_length=4,
        choices=InjuryLocation.choices,
        db_index=True,
        help_text="The location of the injury",
    )
    injury_kind = models.CharField(
        max_length=4,
        choices=InjuryKind.choices,
        db_index=True,
        help_text="The kind of injury",
    )

    injury_description = models.CharField(max_length=100)

    parent_injury = models.ForeignKey(
        "self", on_delete=models.CASCADE, related_name="children_injuries", null=True, blank=True
    )
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


class Illness(ABCEvent):
    class Severity(models.TextChoices):
        LOW = "low", _("Low")
        MODERATE = "moderate", _("Moderate")
        HIGH = "high", _("High")
        CRITICAL = "critical", _("Critical")

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MODERATE)
    is_resolved = models.BooleanField(default=False)


class Intervention(ABCEvent):
    class PerformedByRole(models.TextChoices):
        TRAINEE = "trainee", _("Trainee")
        INSTRUCTOR = "instructor", _("Instructor")
        AI = "ai", _("AI")

    code = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    target = models.CharField(max_length=120, blank=True, default="")
    anatomic_location = models.CharField(max_length=120, blank=True, default="")
    effective = models.BooleanField(null=True, blank=True, default=None)
    performed_by_role = models.CharField(
        max_length=16,
        choices=PerformedByRole.choices,
        default=PerformedByRole.TRAINEE,
    )


class SimulationNote(ABCEvent):
    content = models.TextField(max_length=2000)


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
        help_text="Lock the value to the minimum (instead of a range between min and max)",
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
                condition=models.Q(min_value__lte=models.F("max_value")),
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


class RespiratoryRate(VitalMeasurement):
    @property
    def unit(self):
        return "breaths/min"

    @property
    def friendly_name(self):
        return "Respiratory Rate"

    @property
    def abbreviated_name(self):
        return "RR"


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
                condition=models.Q(min_value_diastolic__lte=models.F("max_value_diastolic")),
                name="bp_dia_min_le_max",
            ),
        ]
