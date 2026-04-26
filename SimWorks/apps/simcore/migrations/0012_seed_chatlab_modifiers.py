from django.db import migrations


def seed_chatlab_modifiers(apps, schema_editor):
    from apps.simcore.modifiers.syncer import sync_lab_modifiers
    sync_lab_modifiers("chatlab")


def reverse_seed(apps, schema_editor):
    ModifierCatalog = apps.get_model("simcore", "ModifierCatalog")
    ModifierCatalog.objects.filter(lab_type="chatlab").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0011_modifier_models"),
    ]

    operations = [
        migrations.RunPython(seed_chatlab_modifiers, reverse_seed),
    ]
