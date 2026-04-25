import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0008_backfill_simulation_accounts"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="simulation",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="simulation",
            name="archived_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("system_failed", "System: Failed"),
                    ("user_archived", "User Archived"),
                    ("staff_archived", "Staff Archived"),
                ],
                db_index=True,
                default="",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="simulation",
            name="archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="archived_simulations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="simulation",
            index=models.Index(
                fields=["status", "archived_at"], name="idx_sim_status_archived"
            ),
        ),
    ]
