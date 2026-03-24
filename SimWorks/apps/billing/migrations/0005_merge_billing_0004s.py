from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0004_normalize_product_codes"),
        ("billing", "0004_rename_subscription_index"),
    ]

    operations = []
