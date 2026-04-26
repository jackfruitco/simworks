"""Unit tests for the simcore modifier resolver."""

import pytest

from apps.simcore.modifiers import (
    UnknownModifierError,
    SelectionConstraintError,
    get_modifier,
    get_modifier_groups,
    render_modifier_prompt,
    resolve_modifiers,
)


@pytest.fixture(autouse=True)
def clear_modifier_cache():
    from apps.simcore.modifiers import _clear_cache
    _clear_cache()
    yield
    _clear_cache()


@pytest.mark.django_db
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


@pytest.mark.django_db
class TestGetModifier:

    def test_returns_definition_for_known_key(self):
        mod = get_modifier("chatlab", "musculoskeletal")
        assert mod is not None
        assert mod.key == "musculoskeletal"
        assert mod.label == "Musculoskeletal"

    def test_returns_none_for_unknown_key(self):
        mod = get_modifier("chatlab", "nonexistent_key_xyz")
        assert mod is None


@pytest.mark.django_db
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

    def test_raises_for_unknown_key(self):
        with pytest.raises(UnknownModifierError, match="nonexistent"):
            resolve_modifiers("chatlab", ["nonexistent_xyz"])

    def test_raises_for_single_select_violation(self):
        with pytest.raises(SelectionConstraintError, match="single-select"):
            resolve_modifiers("chatlab", ["musculoskeletal", "respiratory"])

    def test_allows_one_key_per_single_select_group(self):
        resolved = resolve_modifiers("chatlab", ["respiratory"])
        assert len(resolved) == 1


@pytest.mark.django_db
class TestRenderModifierPrompt:

    def test_renders_prompt_fragment_for_single_key(self):
        prompt = render_modifier_prompt("chatlab", ["musculoskeletal"])
        assert "musculoskeletal" in prompt.lower()

    def test_joins_multiple_fragments_from_different_groups(self):
        prompt = render_modifier_prompt("chatlab", ["respiratory", "acute"])
        assert "respiratory" in prompt.lower()
        assert "acute" in prompt.lower()

    def test_empty_keys_returns_empty_string(self):
        prompt = render_modifier_prompt("chatlab", [])
        assert prompt == ""

    def test_prompt_contains_expected_fragment(self):
        prompt = render_modifier_prompt("chatlab", ["chronic"])
        assert "more than 8 weeks" in prompt
