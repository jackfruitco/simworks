"""Initial migration for the guards app.

Creates SessionPresence and UsageRecord tables.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("simcore", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionPresence",
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
                    "lab_type",
                    models.CharField(
                        choices=[
                            ("trainerlab", "TrainerLab"),
                            ("chatlab", "ChatLab"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "guard_state",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("idle", "Idle"),
                            ("warning", "Warning"),
                            ("paused_inactivity", "Paused (Inactivity)"),
                            ("paused_runtime_cap", "Paused (Runtime Cap)"),
                            ("locked_usage", "Locked (Usage)"),
                            ("ended", "Ended"),
                        ],
                        default="active",
                        max_length=32,
                    ),
                ),
                (
                    "pause_reason",
                    models.CharField(
                        choices=[
                            ("none", "None"),
                            ("inactivity", "Inactivity"),
                            ("runtime_cap", "Runtime Cap"),
                            ("usage_limit", "Usage Limit"),
                            ("wall_clock_expiry", "Wall-Clock Expiry"),
                            ("manual", "Manual"),
                        ],
                        default="none",
                        max_length=32,
                    ),
                ),
                ("last_presence_at", models.DateTimeField(blank=True, null=True)),
                (
                    "client_visibility",
                    models.CharField(
                        choices=[
                            ("foreground", "Foreground"),
                            ("background", "Background"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                (
                    "last_visibility_change_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("paused_at", models.DateTimeField(blank=True, null=True)),
                ("runtime_locked_at", models.DateTimeField(blank=True, null=True)),
                ("warning_sent_at", models.DateTimeField(blank=True, null=True)),
                ("wall_clock_started_at", models.DateTimeField(blank=True, null=True)),
                ("wall_clock_expires_at", models.DateTimeField(blank=True, null=True)),
                ("engine_runnable", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "simulation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="guard_presence",
                        to="simcore.simulation",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["guard_state", "last_presence_at"],
                        name="idx_guard_state_presence",
                    ),
                    models.Index(
                        fields=["lab_type", "guard_state"],
                        name="idx_guard_lab_state",
                    ),
                    models.Index(
                        fields=["engine_runnable"],
                        name="idx_guard_engine_runnable",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UsageRecord",
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
                    "scope_type",
                    models.CharField(
                        choices=[
                            ("session", "Session"),
                            ("user", "User"),
                            ("account", "Account"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "lab_type",
                    models.CharField(
                        choices=[
                            ("trainerlab", "TrainerLab"),
                            ("chatlab", "ChatLab"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "product_code",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("period_start", models.DateTimeField()),
                ("period_end", models.DateTimeField(blank=True, null=True)),
                ("input_tokens", models.PositiveBigIntegerField(default=0)),
                ("output_tokens", models.PositiveBigIntegerField(default=0)),
                ("reasoning_tokens", models.PositiveBigIntegerField(default=0)),
                ("total_tokens", models.PositiveBigIntegerField(default=0)),
                ("service_call_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "simulation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_records",
                        to="simcore.simulation",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_records",
                        to="accounts.account",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["scope_type", "simulation_id"],
                        name="idx_usage_scope_sim",
                    ),
                    models.Index(
                        fields=["scope_type", "user_id", "period_start"],
                        name="idx_usage_scope_user",
                    ),
                    models.Index(
                        fields=["scope_type", "account_id", "period_start"],
                        name="idx_usage_scope_account",
                    ),
                    models.Index(
                        fields=["lab_type", "product_code"],
                        name="idx_usage_lab_product",
                    ),
                ],
            },
        ),
    ]
