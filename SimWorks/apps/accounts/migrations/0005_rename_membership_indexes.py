from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_backfill_personal_accounts"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="accountmembership",
            old_name="idx_account_membership_user_status",
            new_name="idx_acct_mship_user_status",
        ),
        migrations.RenameIndex(
            model_name="accountmembership",
            old_name="idx_account_membership_invite_email",
            new_name="idx_acct_mship_invite_email",
        ),
    ]
