# Generated migration to remove AIResponse and add service_call_attempt FK
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("simulation", "0002_add_ai_response_audit_fk"),
        ("orchestrai_django", "0006_add_service_call_attempt"),
    ]

    operations = [
        # Add service_call_attempt FK to SimulationMetadata
        migrations.AddField(
            model_name="simulationmetadata",
            name="service_call_attempt",
            field=models.ForeignKey(
                blank=True,
                help_text="Link to service call attempt that produced this metadata",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="simulation_metadata",
                to="orchestrai_django.servicecallattempt",
            ),
        ),
        # Update help_text for ai_response_audit (mark as deprecated)
        migrations.AlterField(
            model_name="simulationmetadata",
            name="ai_response_audit",
            field=models.ForeignKey(
                blank=True,
                help_text="Link to AI audit record (deprecated)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="simulation_metadata",
                to="orchestrai_django.airesponseaudit",
            ),
        ),
        # Remove the AIResponse model
        migrations.DeleteModel(
            name="AIResponse",
        ),
    ]
