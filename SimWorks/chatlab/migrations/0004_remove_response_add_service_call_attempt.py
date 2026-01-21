# Generated migration to remove response FK and add service_call_attempt FK
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chatlab", "0003_add_ai_response_audit_fk"),
        ("simulation", "0003_remove_airesponse_add_service_call_attempt"),
        ("orchestrai_django", "0006_add_service_call_attempt"),
    ]

    operations = [
        # Add service_call_attempt FK to Message
        migrations.AddField(
            model_name="message",
            name="service_call_attempt",
            field=models.ForeignKey(
                blank=True,
                help_text="Link to service call attempt that produced this message",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="messages",
                to="orchestrai_django.servicecallattempt",
            ),
        ),
        # Update help_text for ai_response_audit (mark as deprecated)
        migrations.AlterField(
            model_name="message",
            name="ai_response_audit",
            field=models.ForeignKey(
                blank=True,
                help_text="Link to AI audit record that produced this message (deprecated)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="messages",
                to="orchestrai_django.airesponseaudit",
            ),
        ),
        # Remove the response FK (references AIResponse which is being deleted)
        migrations.RemoveField(
            model_name="message",
            name="response",
        ),
    ]
