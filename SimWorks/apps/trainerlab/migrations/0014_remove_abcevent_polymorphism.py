# Hand-written migration — removes django-polymorphic ABCEvent multi-table
# inheritance and replaces every domain type with a standalone flat table.
# Also renames TrainerRuntimeEvent → RuntimeEvent (new table name).
#
# Dev-only: no data migration needed (no production rows to preserve).

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


_SOURCE_CHOICES = [
    ("ai", "AI"),
    ("instructor", "Instructor"),
    ("system", "System"),
]

_INJURY_LOCATION_CHOICES = [
    ("HLA", "Left Anterior Head"),
    ("HRA", "Right Anterior Head"),
    ("HLP", "Left Posterior Head"),
    ("HRP", "Right Posterior Head"),
    ("NLA", "Left Anterior Neck"),
    ("NRA", "Right Anterior Neck"),
    ("NLP", "Left Posterior Neck"),
    ("NRP", "Right Posterior Neck"),
    ("LUA", "Left Upper Arm"),
    ("LLA", "Left Lower Arm"),
    ("LHA", "Left Hand"),
    ("RUA", "Right Upper Arm"),
    ("RLA", "Right Lower Arm"),
    ("RHA", "Right Hand"),
    ("TLA", "Left Anterior Chest"),
    ("TRA", "Right Anterior Chest"),
    ("TLP", "Left Posterior Chest"),
    ("TRP", "Right Posterior Chest"),
    ("ALA", "Left Anterior Abdomen"),
    ("ARA", "Right Anterior Abdomen"),
    ("ALP", "Left Posterior Abdomen"),
    ("ARP", "Right Posterior Abdomen"),
    ("LUL", "Left Upper Leg"),
    ("LLL", "Left Lower Leg"),
    ("LFT", "Left Foot"),
    ("RUL", "Right Upper Leg"),
    ("RLL", "Right Lower Leg"),
    ("RFT", "Right Foot"),
    ("JLX", "Left Junctional Axilla"),
    ("JRX", "Right Junctional Axilla"),
    ("JLI", "Left Junctional Inguinal"),
    ("JRI", "Right Junctional Inguinal"),
    ("JLN", "Left Junctional Neck"),
    ("JRN", "Right Junctional Neck"),
]

_INJURY_KIND_CHOICES = [
    ("AMP", "Amputation"),
    ("PAMP", "Partial Amputation"),
    ("LAC", "Laceration"),
    ("LIC", "Internal Laceration"),
    ("BURN", "Burn"),
    ("PUN", "Puncture"),
    ("PEN", "Penetration"),
    ("GSW", "Gunshot Wound"),
    ("SHR", "Shrapnel"),
]

_MARCH_CHOICES = [
    ("M", "Massive Hemorrhage"),
    ("A", "Airway"),
    ("R", "Respiration"),
    ("C", "Circulatory"),
    ("H1", "Hypothermia"),
    ("H2", "Head Injury"),
    ("PC", "Prolonged Field Care"),
]

_SEVERITY_CHOICES = [
    ("low", "Low"),
    ("moderate", "Moderate"),
    ("high", "High"),
    ("critical", "Critical"),
]

_PROBLEM_KIND_CHOICES = [
    ("injury", "Injury"),
    ("illness", "Illness"),
    ("other", "Other"),
]

_INTERVENTION_TYPE_CHOICES = [
    ("tourniquet", "Tourniquet"),
    ("wound_packing", "Wound Packing"),
    ("pressure_dressing", "Pressure Dressing"),
    ("npa", "Nasopharyngeal Airway"),
    ("opa", "Oropharyngeal Airway"),
    ("needle_decompression", "Needle Decompression"),
    ("surgical_cric", "Surgical Cricothyrotomy"),
    ("junctional_tourniquet", "Junctional Tourniquet"),
    ("hemostatic_agent", "Hemostatic Agent"),
    ("pelvic_binder", "Pelvic Binder"),
    ("iv_access", "IV Access"),
    ("io_access", "IO Access"),
    ("fluid_resuscitation", "Fluid Resuscitation"),
    ("blood_transfusion", "Blood Transfusion / WBCT"),
    ("advanced_airway", "Advanced Airway"),
    ("chest_tube", "Chest Tube / Finger Thoracostomy"),
]

_PERFORMED_BY_CHOICES = [
    ("trainee", "Trainee"),
    ("instructor", "Instructor"),
    ("ai", "AI"),
]

_INTERVENTION_STATUS_CHOICES = [
    ("applied", "Applied"),
    ("adjusted", "Adjusted"),
    ("reassessed", "Reassessed"),
    ("removed", "Removed"),
]

_EFFECTIVENESS_CHOICES = [
    ("unknown", "Unknown"),
    ("effective", "Effective"),
    ("partially_effective", "Partially Effective"),
    ("ineffective", "Ineffective"),
]

_PULSE_LOCATION_CHOICES = [
    ("radial_left", "Radial (Left)"),
    ("radial_right", "Radial (Right)"),
    ("femoral_left", "Femoral (Left)"),
    ("femoral_right", "Femoral (Right)"),
    ("carotid_left", "Carotid (Left)"),
    ("carotid_right", "Carotid (Right)"),
    ("pedal_left", "Pedal (Left)"),
    ("pedal_right", "Pedal (Right)"),
]

_PULSE_DESC_CHOICES = [
    ("strong", "Strong"),
    ("bounding", "Bounding"),
    ("weak", "Weak"),
    ("absent", "Absent"),
    ("thready", "Thready"),
]

_COLOR_DESC_CHOICES = [
    ("pink", "Pink"),
    ("pale", "Pale"),
    ("mottled", "Mottled"),
    ("cyanotic", "Cyanotic"),
    ("flushed", "Flushed"),
]

_CONDITION_DESC_CHOICES = [
    ("dry", "Dry"),
    ("moist", "Moist"),
    ("diaphoretic", "Diaphoretic"),
    ("clammy", "Clammy"),
]

_TEMP_DESC_CHOICES = [
    ("warm", "Warm"),
    ("cool", "Cool"),
    ("cold", "Cold"),
    ("hot", "Hot"),
]


def _base_fields(app_label, model_name):
    """Common BaseDomainEvent fields for each standalone table."""
    return [
        (
            "id",
            models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name="ID",
            ),
        ),
        (
            "simulation",
            models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="simcore.simulation",
            ),
        ),
        (
            "source",
            models.CharField(
                choices=_SOURCE_CHOICES,
                default="system",
                max_length=16,
            ),
        ),
        ("is_active", models.BooleanField(db_index=True, default=True)),
        ("timestamp", models.DateTimeField(auto_now_add=True)),
    ]


class Migration(migrations.Migration):

    dependencies = [
        ("trainerlab", "0013_debriefannotation"),
        ("simcore", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        # ── Phase 1: Drop all old polymorphic tables; remove from state ───────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Vital subclasses first (depend on VitalMeasurement)
                migrations.DeleteModel("HeartRate"),
                migrations.DeleteModel("RespiratoryRate"),
                migrations.DeleteModel("SPO2"),
                migrations.DeleteModel("ETCO2"),
                migrations.DeleteModel("BloodGlucoseLevel"),
                migrations.DeleteModel("BloodPressure"),
                migrations.DeleteModel("VitalMeasurement"),
                # Other subclasses that depend on ABCEvent only
                migrations.DeleteModel("SimulationNote"),
                migrations.DeleteModel("ScenarioBrief"),
                migrations.DeleteModel("PulseAssessment"),
                # Intervention depends on Problem
                migrations.DeleteModel("Intervention"),
                # Problem depends on ABCEvent (cause + ptr)
                migrations.DeleteModel("Problem"),
                # Injury / Illness — simple ABCEvent children
                migrations.DeleteModel("Injury"),
                migrations.DeleteModel("Illness"),
                # ABCEvent base
                migrations.DeleteModel("ABCEvent"),
                # Append-only event stream (independent)
                migrations.DeleteModel("TrainerRuntimeEvent"),
            ],
            database_operations=[
                # Drop vital subclass tables (deepest leaves first)
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_bloodpressure",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_bloodglucoselevel",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_etco2",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_spo2",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_respiratoryrate",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_heartrate",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_vitalmeasurement",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # Drop other ABCEvent children
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_intervention",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_simulationnote",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_scenariobrief",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_pulseassessment",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_problem",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_injury",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_illness",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # ABCEvent base table (all children dropped above)
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_abcevent",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # Drop old runtime event table (recreated with new name below)
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS trainerlab_trainerruntimeevent",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        # ── Phase 2: Create new standalone domain models ──────────────────────
        # Injury — no deps on new models
        migrations.CreateModel(
            name="Injury",
            fields=[
                *_base_fields("trainerlab", "injury"),
                (
                    "injury_location",
                    models.CharField(
                        choices=_INJURY_LOCATION_CHOICES,
                        db_index=True,
                        help_text="The location of the injury",
                        max_length=4,
                    ),
                ),
                (
                    "injury_kind",
                    models.CharField(
                        choices=_INJURY_KIND_CHOICES,
                        db_index=True,
                        help_text="The kind of injury",
                        max_length=4,
                    ),
                ),
                ("injury_description", models.CharField(max_length=100)),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.injury",
                    ),
                ),
            ],
        ),
        # Illness — no deps on new models
        migrations.CreateModel(
            name="Illness",
            fields=[
                *_base_fields("trainerlab", "illness"),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.illness",
                    ),
                ),
            ],
        ),
        # Problem — deps: Injury, Illness
        migrations.CreateModel(
            name="Problem",
            fields=[
                *_base_fields("trainerlab", "problem"),
                (
                    "cause_injury",
                    models.ForeignKey(
                        blank=True,
                        help_text="The underlying Injury cause. Null for illness-based or standalone problems.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="problems",
                        to="trainerlab.injury",
                    ),
                ),
                (
                    "cause_illness",
                    models.ForeignKey(
                        blank=True,
                        help_text="The underlying Illness cause. Null for injury-based or standalone problems.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="problems",
                        to="trainerlab.illness",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        help_text="The Problem record this one replaces.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.problem",
                    ),
                ),
                (
                    "problem_kind",
                    models.CharField(
                        choices=_PROBLEM_KIND_CHOICES,
                        db_index=True,
                        default="other",
                        help_text="Auto-derived from cause type at creation time.",
                        max_length=16,
                    ),
                ),
                (
                    "march_category",
                    models.CharField(
                        choices=_MARCH_CHOICES,
                        db_index=True,
                        max_length=3,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=_SEVERITY_CHOICES,
                        default="moderate",
                        max_length=16,
                    ),
                ),
                ("is_treated", models.BooleanField(default=False)),
                ("is_resolved", models.BooleanField(default=False)),
                ("description", models.TextField(blank=True, default="")),
            ],
        ),
        # Intervention — deps: Problem
        migrations.CreateModel(
            name="Intervention",
            fields=[
                *_base_fields("trainerlab", "intervention"),
                (
                    "intervention_type",
                    models.CharField(
                        blank=True,
                        choices=_INTERVENTION_TYPE_CHOICES,
                        db_index=True,
                        default="",
                        max_length=64,
                    ),
                ),
                (
                    "site_code",
                    models.CharField(blank=True, db_index=True, default="", max_length=64),
                ),
                (
                    "target_problem",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="targeted_by_interventions",
                        to="trainerlab.problem",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.intervention",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=_INTERVENTION_STATUS_CHOICES,
                        default="applied",
                        max_length=24,
                    ),
                ),
                (
                    "effectiveness",
                    models.CharField(
                        choices=_EFFECTIVENESS_CHOICES,
                        default="unknown",
                        max_length=24,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("details_json", models.JSONField(blank=True, default=dict)),
                ("code", models.CharField(blank=True, default="", max_length=64)),
                ("description", models.TextField(blank=True, default="")),
                ("target", models.CharField(blank=True, default="", max_length=120)),
                (
                    "anatomic_location",
                    models.CharField(blank=True, default="", max_length=120),
                ),
                (
                    "performed_by_role",
                    models.CharField(
                        choices=_PERFORMED_BY_CHOICES,
                        default="trainee",
                        max_length=16,
                    ),
                ),
            ],
        ),
        # SimulationNote — no deps on new models
        migrations.CreateModel(
            name="SimulationNote",
            fields=[
                *_base_fields("trainerlab", "simulationnote"),
                ("content", models.TextField(max_length=2000)),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.simulationnote",
                    ),
                ),
            ],
        ),
        # ScenarioBrief — no deps on new models
        migrations.CreateModel(
            name="ScenarioBrief",
            fields=[
                *_base_fields("trainerlab", "scenariobrief"),
                (
                    "read_aloud_brief",
                    models.TextField(
                        help_text="Concise instructor read-aloud brief for the trainee."
                    ),
                ),
                ("environment", models.TextField(blank=True, default="")),
                ("location_overview", models.TextField(blank=True, default="")),
                ("threat_context", models.TextField(blank=True, default="")),
                (
                    "evacuation_options",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Available evacuation or transport options.",
                    ),
                ),
                (
                    "evacuation_time",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "special_considerations",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Other constraints or scenario considerations.",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.scenariobrief",
                    ),
                ),
            ],
        ),
        # HeartRate — standalone vital
        migrations.CreateModel(
            name="HeartRate",
            fields=[
                *_base_fields("trainerlab", "heartrate"),
                (
                    "min_value",
                    models.PositiveSmallIntegerField(
                        help_text="Minimum value for range of this vital sign"
                    ),
                ),
                (
                    "max_value",
                    models.PositiveSmallIntegerField(
                        help_text="Maximum value for range of this vital sign"
                    ),
                ),
                (
                    "lock_value",
                    models.BooleanField(
                        default=False,
                        help_text="Lock the value to the minimum (instead of a range between min and max)",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.heartrate",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="heartrate",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="heartrate_min_le_max",
            ),
        ),
        # RespiratoryRate
        migrations.CreateModel(
            name="RespiratoryRate",
            fields=[
                *_base_fields("trainerlab", "respiratoryrate"),
                (
                    "min_value",
                    models.PositiveSmallIntegerField(
                        help_text="Minimum value for range of this vital sign"
                    ),
                ),
                (
                    "max_value",
                    models.PositiveSmallIntegerField(
                        help_text="Maximum value for range of this vital sign"
                    ),
                ),
                (
                    "lock_value",
                    models.BooleanField(
                        default=False,
                        help_text="Lock the value to the minimum (instead of a range between min and max)",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.respiratoryrate",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="respiratoryrate",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="respiratoryrate_min_le_max",
            ),
        ),
        # SPO2
        migrations.CreateModel(
            name="SPO2",
            fields=[
                *_base_fields("trainerlab", "spo2"),
                (
                    "min_value",
                    models.PositiveSmallIntegerField(
                        help_text="Minimum value for range of this vital sign"
                    ),
                ),
                (
                    "max_value",
                    models.PositiveSmallIntegerField(
                        help_text="Maximum value for range of this vital sign"
                    ),
                ),
                (
                    "lock_value",
                    models.BooleanField(
                        default=False,
                        help_text="Lock the value to the minimum (instead of a range between min and max)",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.spo2",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="spo2",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="spo2_min_le_max",
            ),
        ),
        # ETCO2
        migrations.CreateModel(
            name="ETCO2",
            fields=[
                *_base_fields("trainerlab", "etco2"),
                (
                    "min_value",
                    models.PositiveSmallIntegerField(
                        help_text="Minimum value for range of this vital sign"
                    ),
                ),
                (
                    "max_value",
                    models.PositiveSmallIntegerField(
                        help_text="Maximum value for range of this vital sign"
                    ),
                ),
                (
                    "lock_value",
                    models.BooleanField(
                        default=False,
                        help_text="Lock the value to the minimum (instead of a range between min and max)",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.etco2",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="etco2",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="etco2_min_le_max",
            ),
        ),
        # BloodGlucoseLevel
        migrations.CreateModel(
            name="BloodGlucoseLevel",
            fields=[
                *_base_fields("trainerlab", "bloodglucoselevel"),
                (
                    "min_value",
                    models.PositiveSmallIntegerField(
                        help_text="Minimum value for range of this vital sign"
                    ),
                ),
                (
                    "max_value",
                    models.PositiveSmallIntegerField(
                        help_text="Maximum value for range of this vital sign"
                    ),
                ),
                (
                    "lock_value",
                    models.BooleanField(
                        default=False,
                        help_text="Lock the value to the minimum (instead of a range between min and max)",
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.bloodglucoselevel",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="bloodglucoselevel",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="bloodglucoselevel_min_le_max",
            ),
        ),
        # BloodPressure
        migrations.CreateModel(
            name="BloodPressure",
            fields=[
                *_base_fields("trainerlab", "bloodpressure"),
                (
                    "min_value",
                    models.PositiveSmallIntegerField(
                        help_text="Minimum value for range of this vital sign"
                    ),
                ),
                (
                    "max_value",
                    models.PositiveSmallIntegerField(
                        help_text="Maximum value for range of this vital sign"
                    ),
                ),
                (
                    "lock_value",
                    models.BooleanField(
                        default=False,
                        help_text="Lock the value to the minimum (instead of a range between min and max)",
                    ),
                ),
                ("min_value_diastolic", models.PositiveSmallIntegerField()),
                ("max_value_diastolic", models.PositiveSmallIntegerField()),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.bloodpressure",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="bloodpressure",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="bloodpressure_min_le_max",
            ),
        ),
        migrations.AddConstraint(
            model_name="bloodpressure",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value_diastolic__lte=models.F("max_value_diastolic")),
                name="bp_dia_min_le_max",
            ),
        ),
        # PulseAssessment
        migrations.CreateModel(
            name="PulseAssessment",
            fields=[
                *_base_fields("trainerlab", "pulseassessment"),
                ("location", models.CharField(choices=_PULSE_LOCATION_CHOICES, max_length=20)),
                ("present", models.BooleanField()),
                ("description", models.CharField(choices=_PULSE_DESC_CHOICES, max_length=20)),
                ("color_normal", models.BooleanField()),
                (
                    "color_description",
                    models.CharField(choices=_COLOR_DESC_CHOICES, max_length=20),
                ),
                ("condition_normal", models.BooleanField()),
                (
                    "condition_description",
                    models.CharField(choices=_CONDITION_DESC_CHOICES, max_length=20),
                ),
                ("temperature_normal", models.BooleanField()),
                (
                    "temperature_description",
                    models.CharField(choices=_TEMP_DESC_CHOICES, max_length=20),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.pulseassessment",
                    ),
                ),
            ],
        ),
        # ── Phase 3: RuntimeEvent (replaces TrainerRuntimeEvent) ──────────────
        migrations.CreateModel(
            name="RuntimeEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runtime_events",
                        to="trainerlab.trainersession",
                    ),
                ),
                (
                    "simulation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runtime_events",
                        to="simcore.simulation",
                    ),
                ),
                ("event_type", models.CharField(max_length=120)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "correlation_id",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.runtimeevent",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="runtime_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "trainerlab_runtimeevent",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="runtimeevent",
            index=models.Index(
                fields=["simulation", "created_at"],
                name="idx_runtime_evt_sim",
            ),
        ),
        migrations.AddIndex(
            model_name="runtimeevent",
            index=models.Index(
                fields=["session", "created_at"],
                name="idx_runtime_evt_session",
            ),
        ),
    ]
