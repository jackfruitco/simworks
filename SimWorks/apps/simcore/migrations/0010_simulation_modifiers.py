from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0009_simulation_archival"),
    ]

    operations = [
        migrations.AddField(
            model_name="simulation",
            name="modifiers",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Canonical modifier keys selected at simulation creation",
            ),
        ),
    ]
