"""Unit tests for the simcore modifier catalog loader."""

from django.core.exceptions import ImproperlyConfigured
import pytest
import yaml


@pytest.fixture(autouse=True)
def clear_modifier_cache():
    from apps.simcore.modifiers import _clear_cache

    _clear_cache()
    yield
    _clear_cache()


@pytest.mark.django_db
class TestLoadLabModifierCatalog:
    def test_loads_chatlab_catalog_successfully(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        catalog = load_lab_modifier_catalog("chatlab")
        assert catalog.lab == "chatlab"
        assert catalog.version == 1
        assert len(catalog.groups) == 2

    def test_caches_result_on_second_call(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        first = load_lab_modifier_catalog("chatlab")
        second = load_lab_modifier_catalog("chatlab")
        assert first is second

    def test_clear_cache_forces_reload(self):
        from apps.simcore.modifiers import _clear_cache, load_lab_modifier_catalog

        first = load_lab_modifier_catalog("chatlab")
        _clear_cache()
        second = load_lab_modifier_catalog("chatlab")
        assert first is not second

    def test_raises_on_unknown_lab_type(self):
        from apps.simcore.modifiers import load_lab_modifier_catalog

        with pytest.raises(ImproperlyConfigured, match="No Django app config"):
            load_lab_modifier_catalog("nonexistent_lab_xyz")

    def test_raises_on_missing_yaml(self, tmp_path):
        from django.apps import apps as django_apps

        from apps.simcore.modifiers.loader import load_lab_modifier_catalog

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        try:
            app_config.path = str(tmp_path)
            with pytest.raises(ImproperlyConfigured, match="not found"):
                load_lab_modifier_catalog("chatlab")
        finally:
            app_config.path = original_path

    def test_raises_on_malformed_yaml(self, tmp_path):
        from django.apps import apps as django_apps

        from apps.simcore.modifiers.loader import load_lab_modifier_catalog

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        bad_yaml = tmp_path / "modifiers.yaml"
        bad_yaml.write_text("key: [unclosed bracket", encoding="utf-8")
        try:
            app_config.path = str(tmp_path)
            with pytest.raises(ImproperlyConfigured, match="Malformed YAML"):
                load_lab_modifier_catalog("chatlab")
        finally:
            app_config.path = original_path

    def test_raises_on_lab_mismatch(self, tmp_path):
        from django.apps import apps as django_apps

        from apps.simcore.modifiers.loader import load_lab_modifier_catalog

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        mismatch_yaml = tmp_path / "modifiers.yaml"
        mismatch_yaml.write_text(
            yaml.dump({"lab": "wronglab", "version": 1, "groups": []}),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            with pytest.raises(ImproperlyConfigured, match="does not match"):
                load_lab_modifier_catalog("chatlab")
        finally:
            app_config.path = original_path

    def test_raises_on_invalid_schema(self, tmp_path):
        from django.apps import apps as django_apps

        from apps.simcore.modifiers.loader import load_lab_modifier_catalog

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        # Missing required 'groups' field
        bad_schema = tmp_path / "modifiers.yaml"
        bad_schema.write_text(
            yaml.dump({"lab": "chatlab", "version": 1}),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            with pytest.raises(ImproperlyConfigured, match="Invalid modifier catalog schema"):
                load_lab_modifier_catalog("chatlab")
        finally:
            app_config.path = original_path

    def test_raises_on_unexpected_yaml_field(self, tmp_path):
        from django.apps import apps as django_apps

        from apps.simcore.modifiers.loader import load_lab_modifier_catalog

        app_config = django_apps.get_app_config("chatlab")
        original_path = app_config.path
        extra_field_yaml = tmp_path / "modifiers.yaml"
        extra_field_yaml.write_text(
            yaml.dump(
                {
                    "lab": "chatlab",
                    "version": 1,
                    "unexpected": "typo",
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
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            app_config.path = str(tmp_path)
            with pytest.raises(ImproperlyConfigured, match="Invalid modifier catalog schema"):
                load_lab_modifier_catalog("chatlab")
        finally:
            app_config.path = original_path
