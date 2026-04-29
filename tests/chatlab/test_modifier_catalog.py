"""Integration tests for the ChatLab modifier catalog."""

import pytest


@pytest.fixture(autouse=True)
def clear_modifier_cache():
    from apps.simcore.modifiers import _clear_cache

    _clear_cache()
    yield
    _clear_cache()


@pytest.fixture
def seed_chatlab(db):
    from apps.simcore.modifiers.syncer import sync_lab_modifiers

    sync_lab_modifiers("chatlab")


@pytest.mark.django_db
class TestChatLabModifierCatalog:
    def test_catalog_loads_for_chatlab(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        assert catalog.lab == "chatlab"
        assert catalog.version == 1

    def test_has_two_groups(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        assert len(catalog.groups) == 2

    def test_group_keys(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        keys = {g.key for g in catalog.groups}
        assert keys == {"clinical_scenario", "clinical_duration"}

    def test_clinical_scenario_has_three_modifiers(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        scenario = next(g for g in catalog.groups if g.key == "clinical_scenario")
        assert len(scenario.modifiers) == 3
        mod_keys = {m.key for m in scenario.modifiers}
        assert mod_keys == {"musculoskeletal", "respiratory", "dermatologic"}

    def test_clinical_duration_has_three_modifiers(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        duration = next(g for g in catalog.groups if g.key == "clinical_duration")
        assert len(duration.modifiers) == 3
        mod_keys = {m.key for m in duration.modifiers}
        assert mod_keys == {"acute", "subacute", "chronic"}

    def test_all_modifiers_have_prompt_fragments(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        for group in catalog.groups:
            for mod in group.modifiers:
                assert mod.prompt_fragment, (
                    f"Modifier {mod.key!r} in group {group.key!r} is missing prompt_fragment"
                )

    def test_all_groups_are_single_select(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        for group in catalog.groups:
            assert group.selection.mode == "single", (
                f"Group {group.key!r} expected single-select, got {group.selection.mode!r}"
            )

    def test_all_groups_are_not_required(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        for group in catalog.groups:
            assert group.selection.required is False


@pytest.mark.django_db
class TestChatLabSystemCheck:
    def test_check_passes_with_valid_yaml_and_seeded_db(self, seed_chatlab):
        from apps.chatlab.checks import check_chatlab_modifier_catalog

        errors = check_chatlab_modifier_catalog(None)
        assert errors == []

    def test_check_warns_when_db_not_seeded(self):
        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.models import ModifierCatalog

        # The management command is the supported DB seed path; absent rows warn.
        ModifierCatalog.objects.filter(lab_type="chatlab").delete()
        errors = check_chatlab_modifier_catalog(None)
        ids = [e.id for e in errors]
        assert "chatlab.W001" in ids
        assert "chatlab.E001" not in ids

    def test_check_fails_on_missing_yaml(self, tmp_path):
        from django.apps import apps as django_apps

        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.modifiers import _clear_cache

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        try:
            app_config.path = str(tmp_path)
            _clear_cache()
            errors = check_chatlab_modifier_catalog(None)
            assert len(errors) == 1
            assert errors[0].id == "chatlab.E001"
        finally:
            app_config.path = original_path
            _clear_cache()

    def test_check_fails_on_duplicate_modifier_keys_within_group(self, monkeypatch, seed_chatlab):
        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.modifiers.schemas import (
            ModifierCatalogSchema,
            ModifierDefinitionSchema,
            ModifierGroupSchema,
            SelectionConfigSchema,
        )

        catalog = ModifierCatalogSchema(
            lab="chatlab",
            version=1,
            groups=[
                ModifierGroupSchema(
                    key="clinical_scenario",
                    label="Clinical Scenario",
                    description="",
                    selection=SelectionConfigSchema(mode="single", required=False),
                    modifiers=[
                        ModifierDefinitionSchema(
                            key="duplicate",
                            label="Duplicate One",
                            description="",
                            prompt_fragment="One.",
                        ),
                        ModifierDefinitionSchema(
                            key="duplicate",
                            label="Duplicate Two",
                            description="",
                            prompt_fragment="Two.",
                        ),
                    ],
                )
            ],
        )
        monkeypatch.setattr(
            "apps.simcore.modifiers.loader.load_lab_modifier_catalog",
            lambda lab_type: catalog,
        )

        errors = check_chatlab_modifier_catalog(None)

        assert any(error.id == "chatlab.E003" for error in errors)

    def test_check_fails_on_duplicate_modifier_keys_across_groups(self, monkeypatch, seed_chatlab):
        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.modifiers.schemas import (
            ModifierCatalogSchema,
            ModifierDefinitionSchema,
            ModifierGroupSchema,
            SelectionConfigSchema,
        )

        catalog = ModifierCatalogSchema(
            lab="chatlab",
            version=1,
            groups=[
                ModifierGroupSchema(
                    key="clinical_scenario",
                    label="Clinical Scenario",
                    description="",
                    selection=SelectionConfigSchema(mode="single", required=False),
                    modifiers=[
                        ModifierDefinitionSchema(
                            key="shared",
                            label="Shared Scenario",
                            description="",
                            prompt_fragment="Scenario.",
                        ),
                    ],
                ),
                ModifierGroupSchema(
                    key="clinical_duration",
                    label="Clinical Duration",
                    description="",
                    selection=SelectionConfigSchema(mode="single", required=False),
                    modifiers=[
                        ModifierDefinitionSchema(
                            key="shared",
                            label="Shared Duration",
                            description="",
                            prompt_fragment="Duration.",
                        ),
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            "apps.simcore.modifiers.loader.load_lab_modifier_catalog",
            lambda lab_type: catalog,
        )

        errors = check_chatlab_modifier_catalog(None)

        duplicate_error = next(error for error in errors if error.id == "chatlab.E004")
        assert "shared" in duplicate_error.msg
        assert "clinical_scenario" in duplicate_error.hint
        assert "clinical_duration" in duplicate_error.hint

    def test_check_fails_on_duplicate_active_db_modifier_keys_across_groups(self, seed_chatlab):
        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.models import ModifierDefinition, ModifierGroup

        duration_group = ModifierGroup.objects.get(key="clinical_duration")
        ModifierDefinition.objects.create(
            group=duration_group,
            key="musculoskeletal",
            label="Duplicate Musculoskeletal",
            description="",
            prompt_fragment="Duplicate.",
            is_active=True,
        )

        errors = check_chatlab_modifier_catalog(None)

        duplicate_error = next(error for error in errors if error.id == "chatlab.E005")
        assert "musculoskeletal" in duplicate_error.msg
        assert "clinical_scenario" in duplicate_error.hint
        assert "clinical_duration" in duplicate_error.hint

    def test_check_ignores_inactive_duplicate_db_modifier_key(self, seed_chatlab):
        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.models import ModifierDefinition, ModifierGroup

        duration_group = ModifierGroup.objects.get(key="clinical_duration")
        ModifierDefinition.objects.create(
            group=duration_group,
            key="musculoskeletal",
            label="Inactive Duplicate Musculoskeletal",
            description="",
            prompt_fragment="Duplicate.",
            is_active=False,
        )

        errors = check_chatlab_modifier_catalog(None)

        assert not any(error.id == "chatlab.E005" for error in errors)

    def test_check_ignores_duplicate_db_modifier_key_in_inactive_group(self, seed_chatlab):
        from apps.chatlab.checks import check_chatlab_modifier_catalog
        from apps.simcore.models import ModifierDefinition, ModifierGroup

        duration_group = ModifierGroup.objects.get(key="clinical_duration")
        duration_group.is_active = False
        duration_group.save(update_fields=["is_active"])
        ModifierDefinition.objects.create(
            group=duration_group,
            key="musculoskeletal",
            label="Inactive Group Duplicate Musculoskeletal",
            description="",
            prompt_fragment="Duplicate.",
            is_active=True,
        )

        errors = check_chatlab_modifier_catalog(None)

        assert not any(error.id == "chatlab.E005" for error in errors)
