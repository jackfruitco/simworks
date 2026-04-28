from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0002_seed_conversation_types"),
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
