# Hand-written migration: adds ConversationType + Conversation models
import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("simcore", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationType",
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
                ("slug", models.SlugField(max_length=40, unique=True)),
                ("display_name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                (
                    "icon",
                    models.CharField(
                        blank=True,
                        max_length=50,
                        help_text="Iconify icon identifier, e.g. 'mdi:robot'",
                    ),
                ),
                (
                    "ai_persona",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        help_text="AI persona slug for service dispatch (e.g. 'patient', 'stitch')",
                    ),
                ),
                (
                    "locks_with_simulation",
                    models.BooleanField(
                        default=True,
                        help_text="If True, conversation becomes read-only when simulation ends",
                    ),
                ),
                (
                    "available_in",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Lab apps where this type is available, e.g. ['chatlab', 'trainerlab']",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                "ordering": ["sort_order", "slug"],
                "verbose_name": "Conversation Type",
                "verbose_name_plural": "Conversation Types",
            },
        ),
        migrations.CreateModel(
            name="Conversation",
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
                    "uuid",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "display_name",
                    models.CharField(blank=True, max_length=100),
                ),
                (
                    "display_initials",
                    models.CharField(blank=True, max_length=5),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_archived", models.BooleanField(default=False)),
                (
                    "simulation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conversations",
                        to="simcore.simulation",
                    ),
                ),
                (
                    "conversation_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="conversations",
                        to="simcore.conversationtype",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["simulation", "conversation_type"],
                name="idx_conv_sim_type",
            ),
        ),
    ]
