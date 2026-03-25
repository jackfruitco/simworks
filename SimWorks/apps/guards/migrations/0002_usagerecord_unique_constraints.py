"""Add unique constraints to UsageRecord for concurrency-safe aggregation."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guards", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="usagerecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="session"),
                fields=["scope_type", "simulation_id", "lab_type", "product_code", "period_start"],
                name="uniq_usage_session",
            ),
        ),
        migrations.AddConstraint(
            model_name="usagerecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="user"),
                fields=["scope_type", "user_id", "lab_type", "product_code", "period_start"],
                name="uniq_usage_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="usagerecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="account"),
                fields=["scope_type", "account_id", "lab_type", "product_code", "period_start"],
                name="uniq_usage_account",
            ),
        ),
    ]
