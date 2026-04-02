"""Add future-safe ended-state choices to ``pause_reason`` field.

Adds ``user_ended``, ``admin_ended``, and ``session_expiry`` so the
public ``guard_reason`` vocabulary can distinguish terminal causes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guards", "0003_fix_guard_state_choices"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sessionpresence",
            name="pause_reason",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("inactivity", "Inactivity"),
                    ("runtime_cap", "Runtime Cap"),
                    ("usage_limit", "Usage Limit"),
                    ("wall_clock_expiry", "Wall-Clock Expiry"),
                    ("manual", "Manual"),
                    ("user_ended", "User Ended"),
                    ("admin_ended", "Admin Ended"),
                    ("session_expiry", "Session Expiry"),
                ],
                default="none",
                max_length=32,
            ),
        ),
    ]
