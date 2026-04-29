"""Unit tests for the simcore modifier resolver (DB-backed)."""

import pytest

from apps.simcore.modifiers import (
    SelectionConstraintError,
    UnknownModifierError,
    get_modifier,
    get_modifier_groups,
    render_modifier_prompt,
    render_modifier_prompt_from_snapshot,
    resolve_modifiers,
)


@pytest.fixture
def seed_chatlab(db):
    from apps.simcore.modifiers.syncer import sync_lab_modifiers

    sync_lab_modifiers("chatlab")


@pytest.mark.django_db
@pytest.mark.usefixtures("seed_chatlab")
class TestGetActiveModifierCatalog:
    def test_raises_if_no_catalog_in_db(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.simcore.models import ModifierCatalog
        from apps.simcore.modifiers.resolver import _get_active_catalog

        ModifierCatalog.objects.filter(lab_type="chatlab").delete()
        with pytest.raises(ImproperlyConfigured, match="No active modifier catalog"):
            _get_active_catalog("chatlab")

    def test_raises_if_catalog_is_inactive(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.simcore.models import ModifierCatalog
        from apps.simcore.modifiers.resolver import _get_active_catalog

        ModifierCatalog.objects.filter(lab_type="chatlab").update(is_active=False)
        with pytest.raises(ImproperlyConfigured, match="No active modifier catalog"):
            _get_active_catalog("chatlab")


@pytest.mark.django_db
@pytest.mark.usefixtures("seed_chatlab")
class TestGetModifierGroups:
    def test_returns_list_of_dicts(self):
        groups = get_modifier_groups("chatlab")
        assert isinstance(groups, list)
        assert len(groups) == 2

    def test_each_group_has_required_keys(self):
        groups = get_modifier_groups("chatlab")
        for g in groups:
            assert "key" in g
            assert "label" in g
            assert "description" in g
            assert "selection" in g
            assert "modifiers" in g

    def test_selection_has_mode_and_required(self):
        groups = get_modifier_groups("chatlab")
        for g in groups:
            assert "mode" in g["selection"]
            assert "required" in g["selection"]

    def test_modifiers_have_key_label_description(self):
        groups = get_modifier_groups("chatlab")
        for g in groups:
            for m in g["modifiers"]:
                assert "key" in m
                assert "label" in m
                assert "description" in m

    def test_group_keys_are_snake_case(self):
        groups = get_modifier_groups("chatlab")
        keys = [g["key"] for g in groups]
        assert "clinical_scenario" in keys
        assert "clinical_duration" in keys

    def test_inactive_groups_excluded(self):
        from apps.simcore.models import ModifierGroup

        ModifierGroup.objects.filter(key="clinical_duration").update(is_active=False)
        groups = get_modifier_groups("chatlab")
        keys = [g["key"] for g in groups]
        assert "clinical_duration" not in keys

    def test_inactive_modifiers_excluded(self):
        from apps.simcore.models import ModifierDefinition

        ModifierDefinition.objects.filter(key="musculoskeletal").update(is_active=False)
        groups = get_modifier_groups("chatlab")
        scenario = next(g for g in groups if g["key"] == "clinical_scenario")
        mod_keys = [m["key"] for m in scenario["modifiers"]]
        assert "musculoskeletal" not in mod_keys


@pytest.mark.django_db
@pytest.mark.usefixtures("seed_chatlab")
class TestGetModifier:
    def test_returns_definition_for_known_key(self):
        mod = get_modifier("chatlab", "musculoskeletal")
        assert mod is not None
        assert mod.key == "musculoskeletal"
        assert mod.label == "Musculoskeletal"

    def test_returns_none_for_unknown_key(self):
        mod = get_modifier("chatlab", "nonexistent_key_xyz")
        assert mod is None

    def test_returns_none_for_inactive_modifier(self):
        from apps.simcore.models import ModifierDefinition

        ModifierDefinition.objects.filter(key="musculoskeletal").update(is_active=False)
        mod = get_modifier("chatlab", "musculoskeletal")
        assert mod is None


@pytest.mark.django_db
@pytest.mark.usefixtures("seed_chatlab")
class TestResolveModifiers:
    def test_resolves_valid_keys(self):
        resolved = resolve_modifiers("chatlab", ["musculoskeletal"])
        assert len(resolved) == 1
        assert resolved[0].key == "musculoskeletal"
        assert resolved[0].group_key == "clinical_scenario"

    def test_resolves_keys_from_different_groups(self):
        resolved = resolve_modifiers("chatlab", ["musculoskeletal", "acute"])
        assert len(resolved) == 2
        keys = {r.key for r in resolved}
        assert keys == {"musculoskeletal", "acute"}

    def test_empty_list_returns_empty(self):
        resolved = resolve_modifiers("chatlab", [])
        assert resolved == []

    def test_raises_when_required_group_has_no_selection_for_empty_keys(self):
        from apps.simcore.models import ModifierGroup

        ModifierGroup.objects.filter(key="clinical_scenario").update(required=True)

        with pytest.raises(
            SelectionConstraintError,
            match="Group 'clinical_scenario' is required but no modifier was selected",
        ):
            resolve_modifiers("chatlab", [])

    def test_raises_when_required_group_omitted(self):
        from apps.simcore.models import ModifierGroup

        ModifierGroup.objects.filter(key="clinical_scenario").update(required=True)

        with pytest.raises(
            SelectionConstraintError,
            match="Group 'clinical_scenario' is required but no modifier was selected",
        ):
            resolve_modifiers("chatlab", ["acute"])

    def test_ignores_inactive_required_group(self):
        from apps.simcore.models import ModifierGroup

        ModifierGroup.objects.filter(key="clinical_scenario").update(
            required=True, is_active=False
        )

        resolved = resolve_modifiers("chatlab", [])
        assert resolved == []

    def test_raises_for_unknown_key(self):
        with pytest.raises(UnknownModifierError, match="nonexistent"):
            resolve_modifiers("chatlab", ["nonexistent_xyz"])

    def test_raises_for_single_select_violation(self):
        with pytest.raises(SelectionConstraintError, match="single-select"):
            resolve_modifiers("chatlab", ["musculoskeletal", "respiratory"])

    def test_allows_one_key_per_single_select_group(self):
        resolved = resolve_modifiers("chatlab", ["respiratory"])
        assert len(resolved) == 1

    def test_resolved_definition_has_prompt_fragment(self):
        resolved = resolve_modifiers("chatlab", ["musculoskeletal"])
        assert resolved[0].definition.prompt_fragment is not None


@pytest.mark.django_db
@pytest.mark.usefixtures("seed_chatlab")
class TestRenderModifierPrompt:
    def test_renders_prompt_fragment_for_single_key(self):
        prompt = render_modifier_prompt("chatlab", ["musculoskeletal"])
        assert "musculoskeletal" in prompt.lower()

    def test_joins_multiple_fragments_with_newline(self):
        prompt = render_modifier_prompt("chatlab", ["respiratory", "acute"])
        assert "\n" in prompt
        assert "respiratory" in prompt.lower()
        assert "acute" in prompt.lower()

    def test_empty_keys_returns_empty_string(self):
        prompt = render_modifier_prompt("chatlab", [])
        assert prompt == ""

    def test_prompt_contains_expected_fragment(self):
        prompt = render_modifier_prompt("chatlab", ["chronic"])
        assert "more than 8 weeks" in prompt


class TestRenderModifierPromptFromSnapshot:
    def test_renders_from_snapshot_list(self):
        snapshot = [
            {
                "key": "musculoskeletal",
                "group_key": "clinical_scenario",
                "label": "Musculoskeletal",
                "description": "",
                "prompt_fragment": "Prefer a musculoskeletal case.",
            },
            {
                "key": "acute",
                "group_key": "clinical_duration",
                "label": "Acute",
                "description": "",
                "prompt_fragment": "Patient has had symptoms under 4 weeks.",
            },
        ]
        prompt = render_modifier_prompt_from_snapshot(snapshot)
        assert "musculoskeletal" in prompt.lower()
        assert "4 weeks" in prompt
        assert "\n" in prompt

    def test_empty_snapshot_returns_empty_string(self):
        assert render_modifier_prompt_from_snapshot([]) == ""

    def test_skips_entries_without_prompt_fragment(self):
        snapshot = [
            {
                "key": "musculoskeletal",
                "group_key": "clinical_scenario",
                "label": "Musculoskeletal",
                "description": "",
                "prompt_fragment": "",
            },
            {
                "key": "acute",
                "group_key": "clinical_duration",
                "label": "Acute",
                "description": "",
                "prompt_fragment": "Under 4 weeks.",
            },
        ]
        prompt = render_modifier_prompt_from_snapshot(snapshot)
        assert "musculoskeletal" not in prompt.lower()
        assert "4 weeks" in prompt
