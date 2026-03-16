# Squashed migration — replaces 0001–0011.
# Changes from prior history: parent_injury removed from Injury.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("simcore", "0005_simulation_feedback_retry_count_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── ABCEvent (polymorphic base) ──────────────────────────────────────
        migrations.CreateModel(
            name="ABCEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("ai", "AI"),
                            ("instructor", "Instructor"),
                            ("system", "System"),
                        ],
                        default="system",
                        max_length=16,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "polymorphic_ctype",
                    models.ForeignKey(
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="polymorphic_%(app_label)s.%(class)s_set+",
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "simulation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="simcore.simulation",
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("ai", "AI"), ("instructor", "Instructor"), ("system", "System")],
                        default="system",
                        max_length=16,
                    ),
                ),
                (
                    "supersedes_event",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_domain_events",
                        to="trainerlab.abcevent",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
        ),
        # ── VitalMeasurement (MTI child of ABCEvent) ─────────────────────────
        migrations.CreateModel(
            name="VitalMeasurement",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
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
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        migrations.AddConstraint(
            model_name="vitalmeasurement",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="vital_min_le_max",
            ),
        ),
        # ── Vital subclasses ─────────────────────────────────────────────────
        migrations.CreateModel(
            name="HeartRate",
            fields=[
                (
                    "vitalmeasurement_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.vitalmeasurement",
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.vitalmeasurement",),
        ),
        migrations.CreateModel(
            name="RespiratoryRate",
            fields=[
                (
                    "vitalmeasurement_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.vitalmeasurement",
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.vitalmeasurement",),
        ),
        migrations.CreateModel(
            name="SPO2",
            fields=[
                (
                    "vitalmeasurement_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.vitalmeasurement",
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.vitalmeasurement",),
        ),
        migrations.CreateModel(
            name="ETCO2",
            fields=[
                (
                    "vitalmeasurement_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.vitalmeasurement",
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.vitalmeasurement",),
        ),
        migrations.CreateModel(
            name="BloodGlucoseLevel",
            fields=[
                (
                    "vitalmeasurement_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.vitalmeasurement",
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.vitalmeasurement",),
        ),
        migrations.CreateModel(
            name="BloodPressure",
            fields=[
                (
                    "vitalmeasurement_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.vitalmeasurement",
                    ),
                ),
                ("min_value_diastolic", models.PositiveSmallIntegerField()),
                ("max_value_diastolic", models.PositiveSmallIntegerField()),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.vitalmeasurement",),
        ),
        migrations.AddConstraint(
            model_name="bloodpressure",
            constraint=models.CheckConstraint(
                condition=models.Q(min_value_diastolic__lte=models.F("max_value_diastolic")),
                name="bp_dia_min_le_max",
            ),
        ),
        # ── Injury (immutable cause — no lifecycle fields) ────────────────────
        migrations.CreateModel(
            name="Injury",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
                (
                    "injury_location",
                    models.CharField(
                        choices=[
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
                        ],
                        db_index=True,
                        help_text="The location of the injury",
                        max_length=4,
                    ),
                ),
                (
                    "injury_kind",
                    models.CharField(
                        choices=[
                            ("AMP", "Amputation"),
                            ("PAMP", "Partial Amputation"),
                            ("LAC", "Laceration"),
                            ("LIC", "Internal Laceration"),
                            ("BURN", "Burn"),
                            ("PUN", "Puncture"),
                            ("PEN", "Penetration"),
                            ("GSW", "Gunshot Wound"),
                            ("SHR", "Shrapnel"),
                        ],
                        db_index=True,
                        help_text="The kind of injury",
                        max_length=4,
                    ),
                ),
                ("injury_description", models.CharField(max_length=100)),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        # ── Illness (immutable cause — no lifecycle fields) ───────────────────
        migrations.CreateModel(
            name="Illness",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        # ── Problem (lifecycle owner; links to Injury or Illness cause) ───────
        migrations.CreateModel(
            name="Problem",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
                (
                    "cause",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="problems",
                        to="trainerlab.abcevent",
                    ),
                ),
                (
                    "problem_kind",
                    models.CharField(
                        choices=[
                            ("injury", "Injury"),
                            ("illness", "Illness"),
                            ("other", "Other"),
                        ],
                        db_index=True,
                        default="other",
                        max_length=16,
                    ),
                ),
                (
                    "march_category",
                    models.CharField(
                        choices=[
                            ("M", "Massive Hemorrhage"),
                            ("A", "Airway"),
                            ("R", "Respiration"),
                            ("C", "Circulatory"),
                            ("H1", "Hypothermia"),
                            ("H2", "Head Injury"),
                            ("PC", "Prolonged Field Care"),
                        ],
                        db_index=True,
                        max_length=3,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("moderate", "Moderate"),
                            ("high", "High"),
                            ("critical", "Critical"),
                        ],
                        default="moderate",
                        max_length=16,
                    ),
                ),
                ("is_treated", models.BooleanField(default=False)),
                ("is_resolved", models.BooleanField(default=False)),
                ("description", models.TextField(blank=True, default="")),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        # ── Intervention ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Intervention",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
                (
                    "intervention_type",
                    models.CharField(
                        blank=True,
                        choices=[
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
                        ],
                        db_index=True,
                        default="",
                        max_length=64,
                    ),
                ),
                ("site_code", models.CharField(blank=True, db_index=True, default="", max_length=64)),
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
                    "status",
                    models.CharField(
                        choices=[
                            ("applied", "Applied"),
                            ("adjusted", "Adjusted"),
                            ("reassessed", "Reassessed"),
                            ("removed", "Removed"),
                        ],
                        default="applied",
                        max_length=24,
                    ),
                ),
                (
                    "effectiveness",
                    models.CharField(
                        choices=[
                            ("unknown", "Unknown"),
                            ("effective", "Effective"),
                            ("partially_effective", "Partially Effective"),
                            ("ineffective", "Ineffective"),
                        ],
                        default="unknown",
                        max_length=24,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("details_json", models.JSONField(blank=True, default=dict)),
                ("code", models.CharField(blank=True, default="", max_length=64)),
                ("description", models.TextField(blank=True, default="")),
                ("target", models.CharField(blank=True, default="", max_length=120)),
                ("anatomic_location", models.CharField(blank=True, default="", max_length=120)),
                (
                    "performed_by_role",
                    models.CharField(
                        choices=[
                            ("trainee", "Trainee"),
                            ("instructor", "Instructor"),
                            ("ai", "AI"),
                        ],
                        default="trainee",
                        max_length=16,
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        # ── SimulationNote ───────────────────────────────────────────────────
        migrations.CreateModel(
            name="SimulationNote",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
                ("content", models.TextField(max_length=2000)),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        # ── ScenarioBrief ────────────────────────────────────────────────────
        migrations.CreateModel(
            name="ScenarioBrief",
            fields=[
                (
                    "abcevent_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="trainerlab.abcevent",
                    ),
                ),
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
                ("evacuation_time", models.CharField(blank=True, default="", max_length=255)),
                (
                    "special_considerations",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Other constraints or scenario considerations.",
                    ),
                ),
            ],
            options={"abstract": False, "base_manager_name": "objects"},
            bases=("trainerlab.abcevent",),
        ),
        # ── TrainerSession ───────────────────────────────────────────────────
        migrations.CreateModel(
            name="TrainerSession",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                ("notes", models.TextField(blank=True, null=True)),
                (
                    "simulation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(app_label)s_session",
                        related_query_name="%(app_label)s_session",
                        to="simcore.simulation",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("seeded", "Seeded"),
                            ("running", "Running"),
                            ("paused", "Paused"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="seeded",
                        max_length=16,
                    ),
                ),
                ("scenario_spec_json", models.JSONField(blank=True, default=dict)),
                ("runtime_state_json", models.JSONField(blank=True, default=dict)),
                ("initial_directives", models.TextField(blank=True, default="")),
                ("tick_interval_seconds", models.PositiveSmallIntegerField(default=15)),
                ("tick_nonce", models.PositiveIntegerField(default=0)),
                ("run_started_at", models.DateTimeField(blank=True, null=True)),
                ("run_paused_at", models.DateTimeField(blank=True, null=True)),
                ("run_completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_ai_tick_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"abstract": False},
        ),
        migrations.AddIndex(
            model_name="trainersession",
            index=models.Index(fields=["status"], name="idx_trainer_session_status"),
        ),
        migrations.AddIndex(
            model_name="trainersession",
            index=models.Index(fields=["run_started_at"], name="idx_trainer_session_started"),
        ),
        # ── TrainerCommand ───────────────────────────────────────────────────
        migrations.CreateModel(
            name="TrainerCommand",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="commands",
                        to="trainerlab.trainersession",
                    ),
                ),
                (
                    "command_type",
                    models.CharField(
                        choices=[
                            ("create_session", "Create Session"),
                            ("start", "Start"),
                            ("pause", "Pause"),
                            ("resume", "Resume"),
                            ("stop", "Stop"),
                            ("steer_prompt", "Steer Prompt"),
                            ("inject_event", "Inject Event"),
                            ("adjust_scenario", "Adjust Scenario"),
                            ("apply_preset", "Apply Preset"),
                        ],
                        max_length=32,
                    ),
                ),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processed", "Processed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="trainerlab_commands",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.AddIndex(
            model_name="trainercommand",
            index=models.Index(fields=["session", "issued_at"], name="idx_trainer_cmd_session"),
        ),
        migrations.AddIndex(
            model_name="trainercommand",
            index=models.Index(fields=["status"], name="idx_trainer_cmd_status"),
        ),
        # ── TrainerRunSummary ────────────────────────────────────────────────
        migrations.CreateModel(
            name="TrainerRunSummary",
            fields=[
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
                    "session",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="summary",
                        to="trainerlab.trainersession",
                    ),
                ),
                ("summary_json", models.JSONField(default=dict)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("generator_version", models.CharField(default="v1", max_length=32)),
            ],
        ),
        # ── TrainerRuntimeEvent ──────────────────────────────────────────────
        migrations.CreateModel(
            name="TrainerRuntimeEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runtime_events",
                        to="trainerlab.trainersession",
                    ),
                ),
                (
                    "simulation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trainer_runtime_events",
                        to="simcore.simulation",
                    ),
                ),
                ("event_type", models.CharField(max_length=120)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("correlation_id", models.CharField(blank=True, max_length=100, null=True)),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="superseded_by",
                        to="trainerlab.trainerruntimeevent",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="trainer_runtime_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddIndex(
            model_name="trainerruntimeevent",
            index=models.Index(fields=["simulation", "created_at"], name="idx_trainer_evt_sim"),
        ),
        migrations.AddIndex(
            model_name="trainerruntimeevent",
            index=models.Index(fields=["session", "created_at"], name="idx_trainer_evt_session"),
        ),
        # ── ScenarioInstruction ──────────────────────────────────────────────
        migrations.CreateModel(
            name="ScenarioInstruction",
            fields=[
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
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trainer_scenario_instructions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("title", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True, default="")),
                ("instruction_text", models.TextField(blank=True, default="")),
                ("injuries_json", models.JSONField(blank=True, default=list)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("moderate", "Moderate"),
                            ("high", "High"),
                            ("critical", "Critical"),
                        ],
                        default="moderate",
                        max_length=16,
                    ),
                ),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-modified_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="scenarioinstruction",
            index=models.Index(fields=["owner", "is_active"], name="idx_scenario_owner_active"),
        ),
        migrations.AddIndex(
            model_name="scenarioinstruction",
            index=models.Index(fields=["severity"], name="idx_scenario_severity"),
        ),
        # ── ScenarioInstructionPermission ────────────────────────────────────
        migrations.CreateModel(
            name="ScenarioInstructionPermission",
            fields=[
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
                    "scenario_instruction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="permissions",
                        to="trainerlab.scenarioinstruction",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trainer_scenario_instruction_permissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("can_read", models.BooleanField(default=True)),
                ("can_edit", models.BooleanField(default=False)),
                ("can_delete", models.BooleanField(default=False)),
                ("can_share", models.BooleanField(default=False)),
                ("can_duplicate", models.BooleanField(default=True)),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="granted_trainer_scenario_permissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="scenarioinstructionpermission",
            constraint=models.UniqueConstraint(
                fields=("scenario_instruction", "user"),
                name="uniq_trainer_scenario_permission",
            ),
        ),
        migrations.AddIndex(
            model_name="scenarioinstructionpermission",
            index=models.Index(fields=["user", "can_read"], name="idx_scenario_perm_user_read"),
        ),
        migrations.AddIndex(
            model_name="scenarioinstructionpermission",
            index=models.Index(
                fields=["scenario_instruction", "can_share"],
                name="idx_scenario_perm_share",
            ),
        ),
    ]
