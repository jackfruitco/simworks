import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0010_simulation_modifiers"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModifierCatalog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("lab_type", models.CharField(db_index=True, max_length=50)),
                ("version", models.PositiveSmallIntegerField(default=1)),
                ("source", models.CharField(default="yaml", max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Modifier Catalog",
                "verbose_name_plural": "Modifier Catalogs",
                "ordering": ["lab_type"],
            },
        ),
        migrations.AddConstraint(
            model_name="modifiercatalog",
            constraint=models.UniqueConstraint(
                fields=["lab_type"], name="uniq_modifier_catalog_lab_type"
            ),
        ),
        migrations.CreateModel(
            name="ModifierGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "catalog",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="groups",
                        to="simcore.modifiercatalog",
                    ),
                ),
                ("key", models.CharField(max_length=100)),
                ("label", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "selection_mode",
                    models.CharField(
                        choices=[("single", "Single"), ("multiple", "Multiple")],
                        default="single",
                        max_length=10,
                    ),
                ),
                ("required", models.BooleanField(default=False)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Modifier Group",
                "verbose_name_plural": "Modifier Groups",
                "ordering": ["sort_order", "key"],
            },
        ),
        migrations.AddConstraint(
            model_name="modifiergroup",
            constraint=models.UniqueConstraint(
                fields=["catalog", "key"], name="uniq_modifier_group_catalog_key"
            ),
        ),
        migrations.CreateModel(
            name="ModifierDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="modifiers",
                        to="simcore.modifiergroup",
                    ),
                ),
                ("key", models.CharField(max_length=100)),
                ("label", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("prompt_fragment", models.TextField(blank=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "manually_edited",
                    models.BooleanField(
                        default=False,
                        help_text="If True, sync will not overwrite this row unless --force is used.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Modifier Definition",
                "verbose_name_plural": "Modifier Definitions",
                "ordering": ["sort_order", "key"],
            },
        ),
        migrations.AddConstraint(
            model_name="modifierdefinition",
            constraint=models.UniqueConstraint(
                fields=["group", "key"], name="uniq_modifier_definition_group_key"
            ),
        ),
        migrations.AddField(
            model_name="simulation",
            name="modifier_snapshot",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Snapshot of resolved modifier data at simulation creation time. "
                    "Each entry: {key, group_key, label, description, prompt_fragment}."
                ),
            ),
        ),
    ]
