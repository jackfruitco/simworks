from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from slugify import slugify

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
    SEEDING = "seeding", _("Seeding")
    SEEDED = "seeded", _("Seeded")
    RUNNING = "running", _("Running")
    PAUSED = "paused", _("Paused")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class EventSource(models.TextChoices):
    AI = "ai", _("AI")
    INSTRUCTOR = "instructor", _("Instructor")
    SYSTEM = "system", _("System")


def _normalized_slug(value: str) -> str:
    return slugify(value or "", separator="_")


def _normalized_code(value: str) -> str:
    return _normalized_slug(value).upper()


def _derive_laterality(value: str) -> str:
    normalized = (value or "").upper()
    if "LEFT" in normalized or normalized.startswith("L"):
        return "left"
    if "RIGHT" in normalized or normalized.startswith("R"):
        return "right"
    return ""


# ---------------------------------------------------------------------------
# Abstract base for all typed domain events
# ---------------------------------------------------------------------------


class BaseDomainEvent(models.Model):
    """Abstract base for typed TrainerLab domain models.

    Each concrete subclass gets its own standalone table — no multi-table
    inheritance, no polymorphic JOINs.  Common fields (simulation, source,
    is_active, timestamp) live directly on each table via this abstract base.
    """

    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="+",
    )
    source = models.CharField(
        max_length=16,
        choices=EventSource.choices,
        default=EventSource.SYSTEM,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.__class__.__name__} at {self.timestamp:%H:%M:%S}"


# ---------------------------------------------------------------------------
# Session / command / runtime-event models
# ---------------------------------------------------------------------------


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


class RuntimeEvent(models.Model):
    """Append-only TrainerLab event stream feeding outbox + SSE.

    Replaces TrainerRuntimeEvent.  Every domain state change (vital update,
    condition created, intervention recorded…) and every session lifecycle
    event (session.seeded, run.started, state.updated…) produces one row here.

    Domain model rows (Injury, Problem, Intervention, vitals…) are the source
    of truth for current state.  RuntimeEvent is the append-only audit log and
    SSE delivery mechanism.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        "trainerlab.TrainerSession",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="runtime_events",
    )
    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.CASCADE,
        related_name="runtime_events",
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
        related_name="runtime_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trainerlab_runtimeevent"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["simulation", "created_at"], name="idx_runtime_evt_sim"),
            models.Index(fields=["session", "created_at"], name="idx_runtime_evt_session"),
        ]


class TrainerRunSummary(models.Model):
    session = models.OneToOneField(
        "trainerlab.TrainerSession", on_delete=models.CASCADE, related_name="summary"
    )
    summary_json = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)
    generator_version = models.CharField(max_length=32, default="v1")


# ---------------------------------------------------------------------------
# Scenario presets
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Domain event: causes (Injury, Illness)
# ---------------------------------------------------------------------------


class Injury(BaseDomainEvent):
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
    injury_description = models.CharField(max_length=500)
    kind = models.CharField(max_length=64, blank=True, default="", db_index=True)
    code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="")
    title = models.CharField(max_length=120, blank=True, default="")
    display_name = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    anatomical_location = models.CharField(max_length=120, blank=True, default="")
    laterality = models.CharField(max_length=16, blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    @property
    def cause_kind(self) -> str:
        return "injury"

    def clean(self) -> None:
        super().clean()
        if not self.kind:
            self.kind = _normalized_slug(self.get_injury_kind_display() or self.injury_kind)
        if not self.code:
            self.code = self.injury_kind
        if not self.slug:
            self.slug = _normalized_slug(self.kind or self.code or self.injury_kind)
        if not self.title:
            self.title = self.injury_description
        if not self.display_name:
            self.display_name = self.title
        if not self.description:
            self.description = self.injury_description
        if not self.anatomical_location:
            self.anatomical_location = self.get_injury_location_display()
        if not self.laterality:
            self.laterality = _derive_laterality(self.anatomical_location or self.injury_location)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_injury_kind_display()} at {self.get_injury_location_display()}"


class Illness(BaseDomainEvent):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=64, blank=True, default="", db_index=True)
    code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="")
    title = models.CharField(max_length=120, blank=True, default="")
    display_name = models.CharField(max_length=120, blank=True, default="")
    anatomical_location = models.CharField(max_length=120, blank=True, default="")
    laterality = models.CharField(max_length=16, blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    @property
    def cause_kind(self) -> str:
        return "illness"

    def clean(self) -> None:
        super().clean()
        if not self.kind:
            self.kind = _normalized_slug(self.name)
        if not self.code:
            self.code = _normalized_code(self.name)
        if not self.slug:
            self.slug = _normalized_slug(self.kind or self.name)
        if not self.title:
            self.title = self.name
        if not self.display_name:
            self.display_name = self.title

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Domain event: Problem (condition lifecycle)
# ---------------------------------------------------------------------------


class Problem(BaseDomainEvent):
    """
    A treatable clinical problem owned by a simulation.

    Injury and Illness remain immutable source records. Problem is the mutable
    clinical entity the engine can track as active, treated, controlled, or
    resolved. For the current schema version every Problem must reference exactly
    one direct cause via ``cause_injury`` or ``cause_illness``.

    A future many-to-many or derived/systemic problem model will likely replace
    these two direct cause FKs with a dedicated link model. For now we enforce a
    single direct cause to keep persistence and adjudication deterministic.
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

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        TREATED = "treated", _("Treated")
        CONTROLLED = "controlled", _("Controlled")
        RESOLVED = "resolved", _("Resolved")

    cause_injury = models.ForeignKey(
        "trainerlab.Injury",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problems",
        help_text="The underlying Injury cause. Null for illness-based or standalone problems.",
    )
    cause_illness = models.ForeignKey(
        "trainerlab.Illness",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problems",
        help_text="The underlying Illness cause. Null for injury-based or standalone problems.",
    )
    parent_problem = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_problems",
        help_text=(
            "Optional parent problem for derived/systemic progression while preserving the direct "
            "cause relationship."
        ),
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
        help_text="The Problem record this one replaces.",
    )
    problem_kind = models.CharField(
        max_length=16,
        choices=ProblemKind.choices,
        default=ProblemKind.OTHER,
        db_index=True,
        help_text="Deprecated direct-cause classification; prefer kind/code for problem identity.",
    )
    kind = models.CharField(max_length=64, blank=True, default="", db_index=True)
    code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="", db_index=True)
    title = models.CharField(max_length=120, blank=True, default="")
    display_name = models.CharField(max_length=120, blank=True, default="")
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
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    is_treated = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    description = models.TextField(blank=True, default="")
    anatomical_location = models.CharField(max_length=120, blank=True, default="")
    laterality = models.CharField(max_length=16, blank=True, default="")
    treated_at = models.DateTimeField(blank=True, null=True)
    controlled_at = models.DateTimeField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    previous_status = models.CharField(max_length=16, blank=True, default="")
    triggering_intervention = models.ForeignKey(
        "trainerlab.Intervention",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_problem_updates",
    )
    adjudication_reason = models.CharField(max_length=120, blank=True, default="")
    adjudication_rule_id = models.CharField(max_length=120, blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["simulation", "status"], name="idx_problem_sim_status"),
            models.Index(fields=["simulation", "kind"], name="idx_problem_sim_kind"),
        ]

    @property
    def cause(self):
        """Return the typed cause object (Injury or Illness), or None."""
        return self.cause_injury or self.cause_illness

    @property
    def cause_id(self):
        """Return the PK of the cause object, or None."""
        return self.cause_injury_id or self.cause_illness_id

    @property
    def cause_kind(self) -> str | None:
        if self.cause_injury_id:
            return "injury"
        if self.cause_illness_id:
            return "illness"
        return None

    @property
    def is_controlled(self) -> bool:
        return self.status in {self.Status.CONTROLLED, self.Status.RESOLVED}

    def _sync_status_fields(self) -> None:
        now = timezone.now()
        if self.status == self.Status.ACTIVE:
            self.is_treated = False
            self.is_resolved = False
            self.treated_at = None
            self.controlled_at = None
            self.resolved_at = None
            return
        if self.status == self.Status.TREATED:
            self.is_treated = True
            self.is_resolved = False
            self.treated_at = self.treated_at or now
            self.controlled_at = None
            self.resolved_at = None
            return
        if self.status == self.Status.CONTROLLED:
            self.is_treated = True
            self.is_resolved = False
            self.treated_at = self.treated_at or now
            self.controlled_at = self.controlled_at or now
            self.resolved_at = None
            return
        self.is_treated = True
        self.is_resolved = True
        self.treated_at = self.treated_at or now
        self.controlled_at = self.controlled_at or now
        self.resolved_at = self.resolved_at or now

    def clean(self) -> None:
        super().clean()
        if bool(self.cause_injury_id) == bool(self.cause_illness_id):
            raise ValidationError(
                {
                    "cause_injury": "Problem must reference exactly one direct cause.",
                    "cause_illness": "Problem must reference exactly one direct cause.",
                }
            )
        if self.parent_problem_id:
            if self.parent_problem.simulation_id != self.simulation_id:
                raise ValidationError(
                    {"parent_problem": "parent_problem must belong to the same simulation."}
                )
            if self.parent_problem.cause_kind != self.cause_kind or (
                self.parent_problem.cause_id != self.cause_id
            ):
                raise ValidationError(
                    {
                        "parent_problem": (
                            "Derived problems must preserve the same direct cause as the parent "
                            "problem."
                        )
                    }
                )
        if not self.kind:
            if self.code:
                self.kind = _normalized_slug(self.code)
            elif self.title:
                self.kind = _normalized_slug(self.title)
        if not self.code:
            self.code = self.kind or _normalized_slug(self.title or self.description)
        if not self.slug:
            self.slug = _normalized_slug(self.kind or self.code or self.title)
        if not self.title:
            self.title = self.display_name or self.description or "Clinical problem"
        if not self.display_name:
            self.display_name = self.title
        if not self.anatomical_location and self.cause is not None:
            self.anatomical_location = getattr(self.cause, "anatomical_location", "") or ""
        if not self.laterality:
            self.laterality = _derive_laterality(self.anatomical_location) or _derive_laterality(
                getattr(self.cause, "laterality", "")
            )
        self._sync_status_fields()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Problem ({self.kind or self.problem_kind}, {self.status})"


# ---------------------------------------------------------------------------
# Domain event: RecommendedIntervention
# ---------------------------------------------------------------------------


class RecommendedIntervention(BaseDomainEvent):
    class RecommendationSource(models.TextChoices):
        AI = "ai", _("AI")
        RULES = "rules", _("Rules")
        MERGED = "merged", _("Merged")

    class ValidationStatus(models.TextChoices):
        ACCEPTED = "accepted", _("Accepted")
        NORMALIZED = "normalized", _("Normalized")
        DOWNGRADED = "downgraded", _("Downgraded")
        REJECTED = "rejected", _("Rejected")

    kind = models.CharField(max_length=64, db_index=True)
    code = models.CharField(max_length=64, db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="", db_index=True)
    title = models.CharField(max_length=120)
    display_name = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    target_problem = models.ForeignKey(
        "trainerlab.Problem",
        on_delete=models.CASCADE,
        related_name="recommended_interventions",
    )
    target_injury = models.ForeignKey(
        "trainerlab.Injury",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommended_interventions",
    )
    target_illness = models.ForeignKey(
        "trainerlab.Illness",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommended_interventions",
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    recommendation_source = models.CharField(
        max_length=16,
        choices=RecommendationSource.choices,
        default=RecommendationSource.AI,
    )
    validation_status = models.CharField(
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.ACCEPTED,
        db_index=True,
    )
    normalized_kind = models.CharField(max_length=64, blank=True, default="")
    normalized_code = models.CharField(max_length=64, blank=True, default="")
    rationale = models.TextField(blank=True, default="")
    priority = models.PositiveSmallIntegerField(null=True, blank=True)
    site_code = models.CharField(max_length=64, blank=True, default="")
    site_label = models.CharField(max_length=120, blank=True, default="")
    contraindications_json = models.JSONField(default=list, blank=True)
    warnings_json = models.JSONField(default=list, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["simulation", "validation_status"],
                name="idx_reco_sim_validation",
            ),
            models.Index(fields=["target_problem"], name="idx_reco_target_problem"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.target_problem_id and self.simulation_id != self.target_problem.simulation_id:
            errors["target_problem"] = "target_problem must belong to the same simulation"

        if self.target_injury_id and self.target_illness_id:
            errors["target_injury"] = "Recommendation can only reference one explicit target cause."
            errors["target_illness"] = (
                "Recommendation can only reference one explicit target cause."
            )

        if self.target_problem_id:
            expected_cause = self.target_problem.cause
            if (
                self.target_injury_id
                and expected_cause
                and self.target_injury_id != expected_cause.id
            ):
                errors["target_injury"] = "target_injury must match the target_problem cause"
            if (
                self.target_illness_id
                and expected_cause
                and self.target_illness_id != expected_cause.id
            ):
                errors["target_illness"] = "target_illness must match the target_problem cause"

        if not self.normalized_kind:
            self.normalized_kind = self.kind
        if not self.normalized_code:
            self.normalized_code = self.code
        if not self.slug:
            self.slug = _normalized_slug(self.normalized_kind or self.kind or self.code)
        if not self.display_name:
            self.display_name = self.title
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} -> Problem {self.target_problem_id}"


# ---------------------------------------------------------------------------
# Domain event: AssessmentFinding
# ---------------------------------------------------------------------------


class AssessmentFinding(BaseDomainEvent):
    class Status(models.TextChoices):
        PRESENT = "present", _("Present")
        STABLE = "stable", _("Stable")
        IMPROVING = "improving", _("Improving")
        WORSENING = "worsening", _("Worsening")

    class Severity(models.TextChoices):
        LOW = "low", _("Low")
        MODERATE = "moderate", _("Moderate")
        HIGH = "high", _("High")
        CRITICAL = "critical", _("Critical")

    kind = models.CharField(max_length=64, db_index=True)
    code = models.CharField(max_length=64, db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="", db_index=True)
    title = models.CharField(max_length=120)
    display_name = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PRESENT,
        db_index=True,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.MODERATE,
    )
    anatomical_location = models.CharField(max_length=120, blank=True, default="")
    laterality = models.CharField(max_length=16, blank=True, default="")
    target_problem = models.ForeignKey(
        "trainerlab.Problem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_findings",
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["simulation", "kind"], name="idx_finding_sim_kind"),
            models.Index(fields=["target_problem"], name="idx_finding_problem"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.target_problem_id and self.target_problem.simulation_id != self.simulation_id:
            errors["target_problem"] = "target_problem must belong to the same simulation"
        if not self.slug:
            self.slug = _normalized_slug(self.kind or self.code or self.title)
        if not self.display_name:
            self.display_name = self.title
        if not self.code:
            self.code = self.kind
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} [{self.status}]"


# ---------------------------------------------------------------------------
# Domain event: DiagnosticResult
# ---------------------------------------------------------------------------


class DiagnosticResult(BaseDomainEvent):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        AVAILABLE = "available", _("Available")
        REVIEWED = "reviewed", _("Reviewed")

    kind = models.CharField(max_length=64, db_index=True)
    code = models.CharField(max_length=64, db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="", db_index=True)
    title = models.CharField(max_length=120)
    display_name = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    value_text = models.CharField(max_length=255, blank=True, default="")
    target_problem = models.ForeignKey(
        "trainerlab.Problem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diagnostic_results",
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["simulation", "kind"], name="idx_diag_sim_kind"),
            models.Index(fields=["target_problem"], name="idx_diag_problem"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.target_problem_id and self.target_problem.simulation_id != self.simulation_id:
            errors["target_problem"] = "target_problem must belong to the same simulation"
        if not self.code:
            self.code = self.kind
        if not self.slug:
            self.slug = _normalized_slug(self.kind or self.code or self.title)
        if not self.display_name:
            self.display_name = self.title
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} [{self.status}]"


# ---------------------------------------------------------------------------
# Domain event: ResourceState
# ---------------------------------------------------------------------------


class ResourceState(BaseDomainEvent):
    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        LIMITED = "limited", _("Limited")
        DEPLETED = "depleted", _("Depleted")
        UNAVAILABLE = "unavailable", _("Unavailable")

    kind = models.CharField(max_length=64, db_index=True)
    code = models.CharField(max_length=64, db_index=True)
    slug = models.SlugField(max_length=80, blank=True, default="", db_index=True)
    title = models.CharField(max_length=120)
    display_name = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    quantity_available = models.IntegerField(default=0)
    quantity_unit = models.CharField(max_length=32, blank=True, default="")
    description = models.TextField(blank=True, default="")
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["simulation", "code"], name="idx_resource_sim_code"),
        ]

    def clean(self) -> None:
        super().clean()
        if not self.code:
            self.code = self.kind
        if not self.slug:
            self.slug = _normalized_slug(self.kind or self.code or self.title)
        if not self.display_name:
            self.display_name = self.title

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} [{self.status}]"


# ---------------------------------------------------------------------------
# Domain event: DispositionState
# ---------------------------------------------------------------------------


class DispositionState(BaseDomainEvent):
    class Status(models.TextChoices):
        HOLD = "hold", _("Hold")
        READY = "ready", _("Ready")
        EN_ROUTE = "en_route", _("En Route")
        DELAYED = "delayed", _("Delayed")
        COMPLETE = "complete", _("Complete")

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.HOLD,
        db_index=True,
    )
    transport_mode = models.CharField(max_length=64, blank=True, default="")
    destination = models.CharField(max_length=120, blank=True, default="")
    eta_minutes = models.PositiveIntegerField(null=True, blank=True)
    handoff_ready = models.BooleanField(default=False)
    scene_constraints_json = models.JSONField(default=list, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        indexes = [
            models.Index(fields=["simulation", "status"], name="idx_dispo_sim_status"),
        ]

    def __str__(self):
        return f"Disposition [{self.status}]"


# ---------------------------------------------------------------------------
# Domain event: RecommendationEvaluation
# ---------------------------------------------------------------------------


class RecommendationEvaluation(BaseDomainEvent):
    recommendation = models.ForeignKey(
        "trainerlab.RecommendedIntervention",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations",
    )
    target_problem = models.ForeignKey(
        "trainerlab.Problem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendation_evaluations",
    )
    target_injury = models.ForeignKey(
        "trainerlab.Injury",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendation_evaluations",
    )
    target_illness = models.ForeignKey(
        "trainerlab.Illness",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendation_evaluations",
    )
    raw_kind = models.CharField(max_length=120, blank=True, default="")
    raw_title = models.CharField(max_length=120, blank=True, default="")
    raw_site = models.CharField(max_length=120, blank=True, default="")
    normalized_kind = models.CharField(max_length=64, blank=True, default="")
    normalized_code = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=120, blank=True, default="")
    recommendation_source = models.CharField(
        max_length=16,
        choices=RecommendedIntervention.RecommendationSource.choices,
        default=RecommendedIntervention.RecommendationSource.AI,
    )
    validation_status = models.CharField(
        max_length=16,
        choices=RecommendedIntervention.ValidationStatus.choices,
        default=RecommendedIntervention.ValidationStatus.ACCEPTED,
        db_index=True,
    )
    rationale = models.TextField(blank=True, default="")
    priority = models.PositiveSmallIntegerField(null=True, blank=True)
    warnings_json = models.JSONField(default=list, blank=True)
    contraindications_json = models.JSONField(default=list, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["simulation", "validation_status"], name="idx_reval_sim_status"),
            models.Index(fields=["target_problem"], name="idx_reval_problem"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.rejection_reason:
            self.rejection_reason = self.rejection_reason[:255]
        if self.target_problem_id and self.target_problem.simulation_id != self.simulation_id:
            errors["target_problem"] = "target_problem must belong to the same simulation"
        if self.recommendation_id and self.recommendation.simulation_id != self.simulation_id:
            errors["recommendation"] = "recommendation must belong to the same simulation"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.rejection_reason:
            self.rejection_reason = self.rejection_reason[:255]
        self.full_clean()
        return super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Domain event: Intervention
# ---------------------------------------------------------------------------


class Intervention(BaseDomainEvent):
    class PerformedByRole(models.TextChoices):
        TRAINEE = "trainee", _("Trainee")
        INSTRUCTOR = "instructor", _("Instructor")
        SYSTEM = "system", _("System")

    class InitiatedByType(models.TextChoices):
        USER = "user", _("User")
        INSTRUCTOR = "instructor", _("Instructor")
        SYSTEM = "system", _("System")

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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
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
    initiated_by_type = models.CharField(
        max_length=16,
        choices=InitiatedByType.choices,
        default=InitiatedByType.USER,
        db_index=True,
    )
    initiated_by_id = models.PositiveIntegerField(null=True, blank=True)
    target_problem_previous_status = models.CharField(max_length=16, blank=True, default="")
    target_problem_current_status = models.CharField(max_length=16, blank=True, default="")
    adjudication_reason = models.CharField(max_length=120, blank=True, default="")
    adjudication_rule_id = models.CharField(max_length=120, blank=True, default="")

    def sync_legacy_fields(self) -> None:
        if not self.intervention_type:
            return
        self.code = build_legacy_intervention_code(self.intervention_type, self.details_json)
        self.description = self.notes
        self.target = self.site_code
        if not self.anatomic_location and self.site_code:
            self.anatomic_location = self.site_code

    def clean(self) -> None:
        super().clean()
        errors: dict[str, list[str] | str] = {}

        if self.source == EventSource.AI:
            errors["source"] = (
                "AI cannot create actual performed interventions. "
                "Only user, instructor, or system initiated actions are allowed."
            )

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

        if not self.target_problem_id:
            errors["target_problem"] = "Actual interventions must target a Problem."
        elif self.simulation_id != self.target_problem.simulation_id:
            errors["target_problem"] = "target_problem must belong to the same simulation"

        if self.target_problem_id and self.target_problem.status == Problem.Status.RESOLVED:
            errors["target_problem"] = (
                "Cannot record a new performed intervention against a resolved problem"
            )

        role_map = {
            self.PerformedByRole.TRAINEE: self.InitiatedByType.USER,
            self.PerformedByRole.INSTRUCTOR: self.InitiatedByType.INSTRUCTOR,
            self.PerformedByRole.SYSTEM: self.InitiatedByType.SYSTEM,
        }
        self.performed_by_role = {
            self.InitiatedByType.USER: self.PerformedByRole.TRAINEE,
            self.InitiatedByType.INSTRUCTOR: self.PerformedByRole.INSTRUCTOR,
            self.InitiatedByType.SYSTEM: self.PerformedByRole.SYSTEM,
        }[self.initiated_by_type]
        if self.performed_by_role not in role_map:
            errors["performed_by_role"] = "performed_by_role must map to a non-AI initiated_by_type"

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.sync_legacy_fields()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        if self.intervention_type:
            return (
                f"{self.get_intervention_type_display()} at {self.site_code or 'unspecified site'}"
            )
        return super().__str__()


# ---------------------------------------------------------------------------
# Domain event: SimulationNote, ScenarioBrief
# ---------------------------------------------------------------------------


class SimulationNote(BaseDomainEvent):
    content = models.TextField(max_length=2000)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )


class ScenarioBrief(BaseDomainEvent):
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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    def __str__(self):
        brief_preview = (self.read_aloud_brief or "")[:50]
        return f"ScenarioBrief at {self.timestamp:%H:%M:%S}: {brief_preview}..."


# ---------------------------------------------------------------------------
# Debrief annotation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Domain event: Vital measurements
# ---------------------------------------------------------------------------


class VitalMeasurement(BaseDomainEvent):
    """
    Abstract base for vital signs.

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
        abstract = True


class HeartRate(VitalMeasurement):
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="heartrate_min_le_max",
            ),
        ]

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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="respiratoryrate_min_le_max",
            ),
        ]

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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="spo2_min_le_max",
            ),
        ]

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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="etco2_min_le_max",
            ),
        ]

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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="bloodglucoselevel_min_le_max",
            ),
        ]

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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

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
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="bloodpressure_min_le_max",
            ),
            models.CheckConstraint(
                condition=models.Q(min_value_diastolic__lte=models.F("max_value_diastolic")),
                name="bp_dia_min_le_max",
            ),
        ]


# ---------------------------------------------------------------------------
# Domain event: PulseAssessment
# ---------------------------------------------------------------------------


class PulseAssessment(BaseDomainEvent):
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
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    def __str__(self):
        return (
            f"PulseAssessment {self.timestamp:%H:%M:%S} "
            f"{self.location}: {'present' if self.present else 'absent'} ({self.description})"
        )
