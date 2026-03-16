from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trainerlab", "0011_remove_intervention_invalid_indexes"),
        ("simcore", "__first__"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DebriefAnnotation",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "learning_objective",
                    models.CharField(
                        choices=[
                            ("assessment", "Patient Assessment"),
                            ("hemorrhage_control", "Hemorrhage Control"),
                            ("airway", "Airway Management"),
                            ("breathing", "Breathing / Respiration"),
                            ("circulation", "Circulation / Shock"),
                            ("hypothermia", "Hypothermia Prevention"),
                            ("communication", "Communication / Reporting"),
                            ("triage", "Triage Decision"),
                            ("intervention", "Intervention Technique"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=32,
                    ),
                ),
                ("observation_text", models.TextField(max_length=2000)),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("correct", "Correct"),
                            ("incorrect", "Incorrect"),
                            ("missed", "Missed"),
                            ("improvised", "Improvised"),
                            ("pending", "Pending / Unscored"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("linked_event_id", models.IntegerField(blank=True, null=True)),
                ("elapsed_seconds_at", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="trainerlab_debrief_annotations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="debrief_annotations",
                        to="trainerlab.trainersession",
                    ),
                ),
                (
                    "simulation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="debrief_annotations",
                        to="simcore.simulation",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="debriefannotation",
            index=models.Index(
                fields=["session", "created_at"],
                name="idx_debrief_annotation_session",
            ),
        ),
        migrations.AddIndex(
            model_name="debriefannotation",
            index=models.Index(
                fields=["simulation", "created_at"],
                name="idx_debrief_annotation_sim",
            ),
        ),
    ]
