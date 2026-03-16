from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from polymorphic.models import PolymorphicModel

from apps.simcore.models import BaseSession

from .intervention_dictionary import (
    INTERVENTION_DEFINITIONS,
    build_legacy_intervention_code,
    normalize_intervention_site,
    normalize_intervention_type,
    normalize_site_code,
    validate_intervention_details,
)


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

    def __str__(self):
        return f"{self.get_injury_kind_display()} at {self.get_injury_location_display()}"


class Illness(ABCEvent):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)


class Problem(ABCEvent):
    """
    A treatable clinical problem owned by a simulation.

    Separates the immutable cause (Injury or Illness) from the mutable
    treatment lifecycle. Lifecycle fields (march_category, severity, is_treated,
    is_resolved) live here; cause fields (mechanism, anatomy, illness name) live on
    the linked Injury / Illness.

    ``cause`` is a FK to ABCEvent so both Injury and Illness can be referenced.
    Null cause means a standalone, instructor-injected problem with no underlying
    cause record.

    ``problem_kind`` is derived from the cause type at creation time and stored for
    query/index performance: "injury", "illness", or "other".
    """

    class MARCHCategory(models.TextChoices):
        M = "M", _("Massive Hemorrhage")
        A = "A", _("Airway")
        R = "R", _("Respiration")
        C = "C", _("Circulatory")
        H1 = "H1", _("Hypothermia")
        H2 = "H2", _("Head Injury")
        PFC = "PC", _("Prolonged Field Care")

    class Severity(models.TextChoices):
        LOW = "low", _("Low")
        MODERATE = "moderate", _("Moderate")
        HIGH = "high", _("High")
        CRITICAL = "critical", _("Critical")

    class ProblemKind(models.TextChoices):
        INJURY = "injury", _("Injury")
        ILLNESS = "illness", _("Illness")
        OTHER = "other", _("Other")

    cause = models.ForeignKey(
        "trainerlab.ABCEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problems",
        help_text="The underlying Injury or Illness. Null for standalone problems.",
    )
    problem_kind = models.CharField(
        max_length=16,
        choices=ProblemKind.choices,
        default=ProblemKind.OTHER,
        db_index=True,
        help_text="Auto-derived from cause type at creation time.",
    )
    march_category = models.CharField(
        max_length=3,
        choices=MARCHCategory.choices,
        db_index=True,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.MODERATE,
    )
    is_treated = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    description = models.TextField(blank=True, default="")

    def __str__(self):
        return (
            f"Problem ({self.problem_kind}, {self.march_category}) "
            f"{'resolved' if self.is_resolved else 'active'}"
        )


class Intervention(ABCEvent):
    class PerformedByRole(models.TextChoices):
        TRAINEE = "trainee", _("Trainee")
        INSTRUCTOR = "instructor", _("Instructor")
        AI = "ai", _("AI")

    class Status(models.TextChoices):
        APPLIED = "applied", _("Applied")
        ADJUSTED = "adjusted", _("Adjusted")
        REASSESSED = "reassessed", _("Reassessed")
        REMOVED = "removed", _("Removed")

    class Effectiveness(models.TextChoices):
        UNKNOWN = "unknown", _("Unknown")
        EFFECTIVE = "effective", _("Effective")
        PARTIALLY_EFFECTIVE = "partially_effective", _("Partially Effective")
        INEFFECTIVE = "ineffective", _("Ineffective")

    intervention_type = models.CharField(
        max_length=64,
        choices=[(d.type_code, d.label) for d in INTERVENTION_DEFINITIONS],
        blank=True,
        default="",
        db_index=True,
    )
    site_code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    target_problem = models.ForeignKey(
        "trainerlab.Problem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="targeted_by_interventions",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.APPLIED,
    )
    effectiveness = models.CharField(
        max_length=24,
        choices=Effectiveness.choices,
        default=Effectiveness.UNKNOWN,
    )
    notes = models.TextField(blank=True, default="")
    details_json = models.JSONField(default=dict, blank=True)
    code = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    target = models.CharField(max_length=120, blank=True, default="")
    anatomic_location = models.CharField(max_length=120, blank=True, default="")
    performed_by_role = models.CharField(
        max_length=16,
        choices=PerformedByRole.choices,
        default=PerformedByRole.TRAINEE,
    )

    def sync_legacy_fields(self) -> None:
        if not self.intervention_type:
            return
        self.code = build_legacy_intervention_code(self.intervention_type, self.details_json)
        self.description = self.notes
        self.target = self.site_code

    def clean(self) -> None:
        super().clean()
        errors: dict[str, list[str] | str] = {}

        if self.intervention_type:
            try:
                self.intervention_type = normalize_intervention_type(self.intervention_type)
            except ValueError as exc:
                errors["intervention_type"] = str(exc)
            else:
                if self.site_code:
                    try:
                        self.site_code = normalize_site_code(
                            normalize_intervention_site(self.intervention_type, self.site_code)
                        )
                    except ValueError as exc:
                        errors["site_code"] = str(exc)
                elif self.pk or self.notes or self.code:
                    errors["site_code"] = "site_code is required for structured interventions"

                try:
                    self.details_json = validate_intervention_details(
                        self.intervention_type, self.details_json or {}
                    )
                except ValueError as exc:
                    errors["details_json"] = str(exc)

        if self.target_problem_id and self.simulation_id != self.target_problem.simulation_id:
            errors["target_problem"] = "target_problem must belong to the same simulation"

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        if self.intervention_type:
            return (
                f"{self.get_intervention_type_display()} at {self.site_code or 'unspecified site'}"
            )
        return super().__str__()


class SimulationNote(ABCEvent):
    content = models.TextField(max_length=2000)


class ScenarioBrief(ABCEvent):
    """Instructor-facing scenario brief delivered before simulation begins."""

    read_aloud_brief = models.TextField(
        help_text="Concise instructor read-aloud brief for the trainee.",
    )
    environment = models.TextField(blank=True, default="")
    location_overview = models.TextField(blank=True, default="")
    threat_context = models.TextField(blank=True, default="")
    evacuation_options = models.JSONField(
        default=list,
        blank=True,
        help_text="Available evacuation or transport options.",
    )
    evacuation_time = models.CharField(max_length=255, blank=True, default="")
    special_considerations = models.JSONField(
        default=list,
        blank=True,
        help_text="Other constraints or scenario considerations.",
    )

    def __str__(self):
        brief_preview = (self.read_aloud_brief or "")[:50]
        return f"ScenarioBrief at {self.timestamp:%H:%M:%S}: {brief_preview}..."


class DebriefAnnotation(models.Model):
    """Structured instructor annotation dropped during a live session for debrief anchoring."""

    class LearningObjective(models.TextChoices):
        ASSESSMENT = "assessment", _("Patient Assessment")
        HEMORRHAGE_CONTROL = "hemorrhage_control", _("Hemorrhage Control")
        AIRWAY = "airway", _("Airway Management")
        BREATHING = "breathing", _("Breathing / Respiration")
        CIRCULATION = "circulation", _("Circulation / Shock")
        HYPOTHERMIA = "hypothermia", _("Hypothermia Prevention")
        COMMUNICATION = "communication", _("Communication / Reporting")
        TRIAGE = "triage", _("Triage Decision")
        INTERVENTION = "intervention", _("Intervention Technique")
        OTHER = "other", _("Other")

    class Outcome(models.TextChoices):
        CORRECT = "correct", _("Correct")
        INCORRECT = "incorrect", _("Incorrect")
        MISSED = "missed", _("Missed")
        IMPROVISED = "improvised", _("Improvised")
        PENDING = "pending", _("Pending / Unscored")

    session = models.ForeignKey(
        "trainerlab.TrainerSession",
        on_delete=models.CASCADE,
        related_name="debrief_annotations",
    )
    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="debrief_annotations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trainerlab_debrief_annotations",
    )
    learning_objective = models.CharField(
        max_length=32,
        choices=LearningObjective.choices,
        default=LearningObjective.OTHER,
    )
    observation_text = models.TextField(max_length=2000)
    outcome = models.CharField(
        max_length=16,
        choices=Outcome.choices,
        default=Outcome.PENDING,
    )
    # Optional: link to a specific domain event (e.g. the injury that was missed)
    linked_event_id = models.IntegerField(null=True, blank=True)
    # Allow backdating to a specific elapsed second in the simulation
    elapsed_seconds_at = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["session", "created_at"],
                name="idx_debrief_annotation_session",
            ),
            models.Index(
                fields=["simulation", "created_at"],
                name="idx_debrief_annotation_sim",
            ),
        ]

    def __str__(self):
        return f"{self.get_learning_objective_display()} [{self.get_outcome_display()}]"


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


class PulseAssessment(ABCEvent):
    """Pulse assessment at a specific anatomic site.

    Records pulse presence, quality, and peripheral perfusion indicators
    (skin color, condition, temperature) at each anatomic location.
    """

    class Location(models.TextChoices):
        RADIAL_LEFT = "radial_left", "Radial (Left)"
        RADIAL_RIGHT = "radial_right", "Radial (Right)"
        FEMORAL_LEFT = "femoral_left", "Femoral (Left)"
        FEMORAL_RIGHT = "femoral_right", "Femoral (Right)"
        CAROTID_LEFT = "carotid_left", "Carotid (Left)"
        CAROTID_RIGHT = "carotid_right", "Carotid (Right)"
        PEDAL_LEFT = "pedal_left", "Pedal (Left)"
        PEDAL_RIGHT = "pedal_right", "Pedal (Right)"

    class Description(models.TextChoices):
        STRONG = "strong", "Strong"
        BOUNDING = "bounding", "Bounding"
        WEAK = "weak", "Weak"
        ABSENT = "absent", "Absent"
        THREADY = "thready", "Thready"

    class ColorDescription(models.TextChoices):
        PINK = "pink", "Pink"
        PALE = "pale", "Pale"
        MOTTLED = "mottled", "Mottled"
        CYANOTIC = "cyanotic", "Cyanotic"
        FLUSHED = "flushed", "Flushed"

    class ConditionDescription(models.TextChoices):
        DRY = "dry", "Dry"
        MOIST = "moist", "Moist"
        DIAPHORETIC = "diaphoretic", "Diaphoretic"
        CLAMMY = "clammy", "Clammy"

    class TemperatureDescription(models.TextChoices):
        WARM = "warm", "Warm"
        COOL = "cool", "Cool"
        COLD = "cold", "Cold"
        HOT = "hot", "Hot"

    location = models.CharField(max_length=20, choices=Location.choices)
    present = models.BooleanField()
    description = models.CharField(max_length=20, choices=Description.choices)

    color_normal = models.BooleanField()
    color_description = models.CharField(max_length=20, choices=ColorDescription.choices)

    condition_normal = models.BooleanField()
    condition_description = models.CharField(max_length=20, choices=ConditionDescription.choices)

    temperature_normal = models.BooleanField()
    temperature_description = models.CharField(
        max_length=20, choices=TemperatureDescription.choices
    )

    def __str__(self):
        return (
            f"PulseAssessment {self.timestamp:%H:%M:%S} "
            f"{self.location}: {'present' if self.present else 'absent'} ({self.description})"
        )

    class Meta:
        pass
