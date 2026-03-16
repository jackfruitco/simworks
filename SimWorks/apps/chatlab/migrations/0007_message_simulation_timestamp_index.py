# Generated migration for composite index on Message(simulation_id, timestamp)

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("chatlab", "0006_message_source_message_and_dedupe"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["simulation", "timestamp"],
                name="chatlab_msg_sim_ts_idx",
            ),
        ),
    ]
