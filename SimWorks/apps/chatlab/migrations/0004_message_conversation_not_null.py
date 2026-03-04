# Hand-written migration: make Message.conversation non-nullable
# This runs AFTER the data migration has backfilled all existing messages.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("chatlab", "0003_message_conversation"),
        ("simcore", "0003_seed_conversation_types"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="conversation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="simcore.conversation",
            ),
        ),
    ]
