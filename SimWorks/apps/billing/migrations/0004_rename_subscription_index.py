from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_backfill_legacy_lab_memberships"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="subscription",
            old_name="idx_subscription_account_status",
            new_name="idx_sub_account_status",
        ),
    ]
