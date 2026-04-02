"""Add missing ``paused_manual`` choice to ``guard_state`` field.

The initial migration omitted ``paused_manual`` from the choices list
while the model and enums included it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guards", "0002_usagerecord_unique_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sessionpresence",
            name="guard_state",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("idle", "Idle"),
                    ("warning", "Warning"),
                    ("paused_inactivity", "Paused (Inactivity)"),
                    ("paused_manual", "Paused (Manual)"),
                    ("paused_runtime_cap", "Paused (Runtime Cap)"),
                    ("locked_usage", "Locked (Usage)"),
                    ("ended", "Ended"),
                ],
                default="active",
                max_length=32,
            ),
        ),
    ]
