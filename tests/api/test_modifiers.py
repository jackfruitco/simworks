"""Tests for modifier API endpoints."""

import pytest
from django.test import Client


@pytest.mark.django_db
class TestListModifierGroups:
    """Tests for GET /api/v1/config/modifier-groups/."""

    def test_list_all_modifier_groups_defaults_to_chatlab(self):
        """Returns chatlab modifier groups when no lab_type specified."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        group_keys = [g["key"] for g in data]
        assert "clinical_scenario" in group_keys
        assert "clinical_duration" in group_keys

    def test_explicit_chatlab_lab_type(self):
        """Explicit lab_type=chatlab returns same as default."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?lab_type=chatlab")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_unknown_lab_type_returns_400(self):
        """Unknown lab_type returns 400."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?lab_type=nonexistent")

        assert response.status_code == 400

    def test_modifier_group_structure(self):
        """Response has correct structure with new fields."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?lab_type=chatlab")

        assert response.status_code == 200
        data = response.json()

        group = data[0]
        assert "key" in group
        assert "label" in group
        assert "description" in group
        assert "selection" in group
        assert "modifiers" in group
        assert "mode" in group["selection"]
        assert "required" in group["selection"]

    def test_modifier_structure_has_label(self):
        """Each modifier includes key, label, and description."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?lab_type=chatlab")

        assert response.status_code == 200
        data = response.json()

        modifier = data[0]["modifiers"][0]
        assert "key" in modifier
        assert "label" in modifier
        assert "description" in modifier

    def test_clinical_scenario_group_has_three_modifiers(self):
        """Clinical scenario group contains musculoskeletal, respiratory, dermatologic."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?lab_type=chatlab")

        assert response.status_code == 200
        data = response.json()

        scenario_group = next(g for g in data if g["key"] == "clinical_scenario")
        mod_keys = [m["key"] for m in scenario_group["modifiers"]]
        assert "musculoskeletal" in mod_keys
        assert "respiratory" in mod_keys
        assert "dermatologic" in mod_keys

    def test_selection_mode_is_single_for_both_groups(self):
        """Both groups are single-select."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?lab_type=chatlab")

        assert response.status_code == 200
        data = response.json()

        for group in data:
            assert group["selection"]["mode"] == "single"
