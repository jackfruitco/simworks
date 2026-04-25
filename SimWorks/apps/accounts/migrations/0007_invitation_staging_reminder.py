from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_invitation_access_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="staging_setup_reminder_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
