import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0009_simulation_archival"),
        ("trainerlab", "0021_traineridempotencyclaim"),
    ]

    operations = [
        migrations.CreateModel(
            name="SimulationFailureRecord",
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("environment", models.CharField(blank=True, db_index=True, default="", max_length=32)),
                ("lab_slug", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                (
                    "simulation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="failure_record",
                        to="simcore.simulation",
                    ),
                ),
                (
                    "trainer_session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="failure_records",
                        to="trainerlab.trainersession",
                    ),
                ),
                ("user_id", models.IntegerField(blank=True, null=True)),
                ("account_id", models.IntegerField(blank=True, null=True)),
                ("simulation_status", models.CharField(blank=True, default="", max_length=24)),
                ("session_status", models.CharField(blank=True, default="", max_length=16)),
                ("terminal_reason_code", models.CharField(blank=True, default="", max_length=100)),
                ("terminal_reason_text", models.TextField(blank=True, default="")),
                ("exception_class", models.CharField(blank=True, default="", max_length=255)),
                ("exception_message", models.TextField(blank=True, default="")),
                ("traceback_text", models.TextField(blank=True, default="")),
                (
                    "correlation_id",
                    models.CharField(blank=True, db_index=True, default="", max_length=100),
                ),
                ("service_call_id", models.CharField(blank=True, default="", max_length=100)),
                ("retryable", models.BooleanField(default=True)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["environment", "lab_slug", "created_at"],
                        name="idx_failure_env_lab",
                    ),
                ],
            },
        ),
    ]
