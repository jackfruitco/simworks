from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0005_rename_membership_indexes"),
        ("simcore", "0008_backfill_simulation_accounts"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserFeedback",
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
                ("lab_type", models.CharField(blank=True, default="", max_length=32)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("bug_report", "Bug Report"),
                            ("ux_issue", "UX Issue"),
                            ("simulation_content", "Simulation Content"),
                            ("feature_request", "Feature Request"),
                            ("other", "Other"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("in_app", "In App"),
                            ("testflight", "TestFlight"),
                            ("admin", "Admin"),
                            ("api", "API"),
                            ("unknown", "Unknown"),
                        ],
                        db_index=True,
                        default="in_app",
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("triaged", "Triaged"),
                            ("planned", "Planned"),
                            ("resolved", "Resolved"),
                            ("wont_fix", "Won't Fix"),
                            ("duplicate", "Duplicate"),
                        ],
                        db_index=True,
                        default="new",
                        max_length=32,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                            ("critical", "Critical"),
                        ],
                        default="",
                        max_length=32,
                    ),
                ),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("body", models.TextField()),
                ("rating", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("allow_follow_up", models.BooleanField(default=True)),
                (
                    "client_platform",
                    models.CharField(
                        choices=[
                            ("ios", "iOS"),
                            ("web", "Web"),
                            ("android", "Android"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=32,
                    ),
                ),
                ("client_version", models.CharField(blank=True, default="", max_length=100)),
                ("os_version", models.CharField(blank=True, default="", max_length=100)),
                ("device_model", models.CharField(blank=True, default="", max_length=100)),
                ("request_id", models.CharField(blank=True, default="", max_length=255)),
                ("session_identifier", models.CharField(blank=True, default="", max_length=255)),
                ("context_json", models.JSONField(blank=True, default=dict)),
                ("attachments_json", models.JSONField(blank=True, default=list)),
                ("internal_notes", models.TextField(blank=True, default="")),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedback_submissions",
                        to="accounts.account",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="user_feedback",
                        to="simcore.conversation",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_feedback",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "simulation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="user_feedback",
                        to="simcore.simulation",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedback_submissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "User Feedback",
                "verbose_name_plural": "User Feedback",
                "ordering": ["-created_at"],
            },
        ),
    ]
