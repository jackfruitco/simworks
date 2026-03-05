# Hand-written migration: adds Message.conversation FK (nullable for now)
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("chatlab", "0002_initial"),
        ("simcore", "0002_conversation_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="conversation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="simcore.conversation",
            ),
        ),
    ]
