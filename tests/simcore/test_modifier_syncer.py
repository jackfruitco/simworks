"""Tests for the modifier syncer (YAML→DB sync)."""

import pytest


@pytest.fixture(autouse=True)
def clear_modifier_cache():
    from apps.simcore.modifiers import _clear_cache

    _clear_cache()
    yield
    _clear_cache()


@pytest.mark.django_db
class TestSyncLabModifiers:
    def test_creates_catalog_on_first_run(self):
        from apps.simcore.models import ModifierCatalog
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        # Start empty to test the explicit management-command sync path.
        ModifierCatalog.objects.filter(lab_type="chatlab").delete()
        assert not ModifierCatalog.objects.filter(lab_type="chatlab").exists()
        sync_lab_modifiers("chatlab")
        assert ModifierCatalog.objects.filter(lab_type="chatlab", is_active=True).exists()

    def test_creates_groups_and_definitions(self):
        from apps.simcore.models import ModifierCatalog, ModifierDefinition, ModifierGroup
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")
        catalog = ModifierCatalog.objects.get(lab_type="chatlab")
        assert ModifierGroup.objects.filter(catalog=catalog).count() == 2
        assert ModifierDefinition.objects.filter(group__catalog=catalog).count() == 6

    def test_summary_counts_on_first_sync(self):
        from apps.simcore.models import ModifierCatalog
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        ModifierCatalog.objects.filter(lab_type="chatlab").delete()
        summary = sync_lab_modifiers("chatlab")
        assert summary["groups_created"] == 2
        assert summary["defs_created"] == 6
        assert summary["groups_updated"] == 0
        assert summary["defs_updated"] == 0

    def test_live_sync_rolls_back_partial_writes(self):
        from unittest.mock import patch

        from apps.simcore.models import ModifierCatalog, ModifierGroup
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        ModifierCatalog.objects.filter(lab_type="chatlab").delete()

        with (
            patch.object(
                ModifierGroup.objects,
                "get_or_create",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            sync_lab_modifiers("chatlab")

        assert not ModifierCatalog.objects.filter(lab_type="chatlab").exists()
        assert not ModifierGroup.objects.filter(catalog__lab_type="chatlab").exists()

    def test_is_idempotent(self):
        from apps.simcore.models import ModifierCatalog, ModifierDefinition, ModifierGroup
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")
        sync_lab_modifiers("chatlab")
        catalog = ModifierCatalog.objects.get(lab_type="chatlab")
        assert ModifierGroup.objects.filter(catalog=catalog).count() == 2
        assert ModifierDefinition.objects.filter(group__catalog=catalog).count() == 6

    def test_second_sync_creates_nothing_new(self):
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")
        summary = sync_lab_modifiers("chatlab")
        assert summary["groups_created"] == 0
        assert summary["defs_created"] == 0

    def test_does_not_overwrite_manually_edited_without_force(self):
        from apps.simcore.models import ModifierDefinition
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")
        mod = ModifierDefinition.objects.get(key="musculoskeletal")
        mod.label = "Custom Label"
        mod.manually_edited = True
        mod.save(update_fields=["label", "manually_edited"])

        summary = sync_lab_modifiers("chatlab")
        assert summary["defs_skipped"] == 1
        mod.refresh_from_db()
        assert mod.label == "Custom Label"

    def test_overwrites_manually_edited_with_force(self):
        from apps.simcore.models import ModifierDefinition
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")
        mod = ModifierDefinition.objects.get(key="musculoskeletal")
        mod.label = "Custom Label"
        mod.manually_edited = True
        mod.save(update_fields=["label", "manually_edited"])

        sync_lab_modifiers("chatlab", force=True)
        mod.refresh_from_db()
        assert mod.label == "Musculoskeletal"

    def test_deactivates_groups_removed_from_yaml(self, tmp_path):
        from django.apps import apps as django_apps
        import yaml

        from apps.simcore.models import ModifierCatalog, ModifierGroup
        from apps.simcore.modifiers import _clear_cache
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")

        # Write a YAML with only one group
        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        reduced_yaml = tmp_path / "modifiers.yaml"
        reduced_yaml.write_text(
            yaml.dump(
                {
                    "lab": "chatlab",
                    "version": 2,
                    "groups": [
                        {
                            "key": "clinical_scenario",
                            "label": "Clinical Scenario",
                            "description": "",
                            "selection": {"mode": "single", "required": False},
                            "modifiers": [
                                {
                                    "key": "musculoskeletal",
                                    "label": "Musculoskeletal",
                                    "description": "",
                                    "prompt_fragment": "Prefer musculoskeletal.",
                                },
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            _clear_cache()
            sync_lab_modifiers("chatlab")
        finally:
            app_config.path = original_path
            _clear_cache()

        catalog = ModifierCatalog.objects.get(lab_type="chatlab")
        duration_group = ModifierGroup.objects.get(catalog=catalog, key="clinical_duration")
        assert not duration_group.is_active

    def test_deactivates_modifiers_removed_from_yaml(self, tmp_path):
        from django.apps import apps as django_apps
        import yaml

        from apps.simcore.models import ModifierCatalog, ModifierDefinition, ModifierGroup
        from apps.simcore.modifiers import _clear_cache
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        reduced_yaml = tmp_path / "modifiers.yaml"
        reduced_yaml.write_text(
            yaml.dump(
                {
                    "lab": "chatlab",
                    "version": 2,
                    "groups": [
                        {
                            "key": "clinical_scenario",
                            "label": "Clinical Scenario",
                            "description": "",
                            "selection": {"mode": "single", "required": False},
                            "modifiers": [
                                {
                                    "key": "musculoskeletal",
                                    "label": "Musculoskeletal",
                                    "description": "",
                                    "prompt_fragment": "Prefer musculoskeletal.",
                                },
                            ],
                        },
                        {
                            "key": "clinical_duration",
                            "label": "Clinical Duration",
                            "description": "",
                            "selection": {"mode": "single", "required": False},
                            "modifiers": [
                                {
                                    "key": "acute",
                                    "label": "Acute",
                                    "description": "",
                                    "prompt_fragment": "Under 4 weeks.",
                                },
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            _clear_cache()
            sync_lab_modifiers("chatlab")
        finally:
            app_config.path = original_path
            _clear_cache()

        catalog = ModifierCatalog.objects.get(lab_type="chatlab")
        scenario_group = ModifierGroup.objects.get(catalog=catalog, key="clinical_scenario")
        respiratory = ModifierDefinition.objects.get(group=scenario_group, key="respiratory")
        assert not respiratory.is_active

    def test_never_deletes_rows(self, tmp_path):
        from django.apps import apps as django_apps
        import yaml

        from apps.simcore.models import ModifierDefinition
        from apps.simcore.modifiers import _clear_cache
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")
        original_count = ModifierDefinition.objects.filter(
            group__catalog__lab_type="chatlab"
        ).count()

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        minimal_yaml = tmp_path / "modifiers.yaml"
        minimal_yaml.write_text(
            yaml.dump(
                {
                    "lab": "chatlab",
                    "version": 2,
                    "groups": [
                        {
                            "key": "clinical_scenario",
                            "label": "Clinical Scenario",
                            "description": "",
                            "selection": {"mode": "single", "required": False},
                            "modifiers": [
                                {
                                    "key": "musculoskeletal",
                                    "label": "Musculoskeletal",
                                    "description": "",
                                    "prompt_fragment": "Prefer musculoskeletal.",
                                },
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            _clear_cache()
            sync_lab_modifiers("chatlab")
        finally:
            app_config.path = original_path
            _clear_cache()

        # Row count must not decrease — only is_active changes
        assert (
            ModifierDefinition.objects.filter(group__catalog__lab_type="chatlab").count()
            == original_count
        )

    def test_dry_run_does_not_write(self):
        from apps.simcore.models import ModifierCatalog
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        # Clear existing data to test the "no catalog" dry-run path
        ModifierCatalog.objects.filter(lab_type="chatlab").delete()
        summary = sync_lab_modifiers("chatlab", dry_run=True)
        assert not ModifierCatalog.objects.filter(lab_type="chatlab").exists()
        assert summary["groups_created"] == 2
        assert summary["defs_created"] == 6

    def test_updates_group_label_when_changed(self, tmp_path):
        from django.apps import apps as django_apps
        import yaml

        from apps.simcore.models import ModifierCatalog, ModifierGroup
        from apps.simcore.modifiers import _clear_cache
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        sync_lab_modifiers("chatlab")

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        updated_yaml = tmp_path / "modifiers.yaml"
        updated_yaml.write_text(
            yaml.dump(
                {
                    "lab": "chatlab",
                    "version": 1,
                    "groups": [
                        {
                            "key": "clinical_scenario",
                            "label": "Updated Scenario Label",
                            "description": "",
                            "selection": {"mode": "single", "required": False},
                            "modifiers": [
                                {
                                    "key": "musculoskeletal",
                                    "label": "Musculoskeletal",
                                    "description": "",
                                    "prompt_fragment": "Prefer musculoskeletal.",
                                },
                            ],
                        },
                        {
                            "key": "clinical_duration",
                            "label": "Clinical Duration",
                            "description": "Simulation time constraints",
                            "selection": {"mode": "single", "required": False},
                            "modifiers": [
                                {
                                    "key": "acute",
                                    "label": "Acute",
                                    "description": "New concerns beginning within last 4 weeks",
                                    "prompt_fragment": "The patient's presenting complaint has been occurring for less than 4 weeks (acute).",
                                },
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            _clear_cache()
            summary = sync_lab_modifiers("chatlab")
        finally:
            app_config.path = original_path
            _clear_cache()

        catalog = ModifierCatalog.objects.get(lab_type="chatlab")
        group = ModifierGroup.objects.get(catalog=catalog, key="clinical_scenario")
        assert group.label == "Updated Scenario Label"
        assert summary["groups_updated"] == 1
