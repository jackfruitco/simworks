from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trainerlab", "0020_remove_patientstatusstate_narrative_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TrainerIdempotencyClaim",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
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
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="trainerlab_idempotency_claims",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.CASCADE,
                        related_name="idempotency_claims",
                        to="trainerlab.trainersession",
                    ),
                ),
            ],
            options={},
        ),
        migrations.AddIndex(
            model_name="traineridempotencyclaim",
            index=models.Index(
                fields=["command_type", "issued_at"],
                name="idx_trainer_claim_type",
            ),
        ),
        migrations.AddIndex(
            model_name="traineridempotencyclaim",
            index=models.Index(
                fields=["session", "issued_at"],
                name="idx_trainer_claim_session",
            ),
        ),
    ]
