"""Tests for modifier API endpoints.

Tests:
1. List all modifier groups
2. Filter by specific group names
3. GraphQL endpoint returns 404
"""

from django.test import Client
import pytest


@pytest.mark.django_db
class TestListModifierGroups:
    """Tests for GET /config/modifier-groups/."""

    def test_list_all_modifier_groups(self):
        """Returns all modifier groups when no filter specified."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3  # ClinicalScenario, ClinicalDuration, Feedback

        group_names = [g["group"] for g in data]
        assert "ClinicalScenario" in group_names
        assert "ClinicalDuration" in group_names
        assert "Feedback" in group_names

    def test_filter_by_single_group(self):
        """Can filter by a single group name."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?groups=ClinicalScenario")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["group"] == "ClinicalScenario"
        assert len(data[0]["modifiers"]) == 3  # emergency, outpatient, inpatient

    def test_filter_by_multiple_groups(self):
        """Can filter by multiple group names."""
        client = Client()
        response = client.get(
            "/api/v1/config/modifier-groups/?groups=ClinicalScenario&groups=ClinicalDuration"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        group_names = [g["group"] for g in data]
        assert "ClinicalScenario" in group_names
        assert "ClinicalDuration" in group_names
        assert "Feedback" not in group_names

    def test_filter_nonexistent_group_returns_empty(self):
        """Filtering by non-existent group returns empty list."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?groups=NonExistent")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_modifier_group_structure(self):
        """Response has correct structure."""
        client = Client()
        response = client.get("/api/v1/config/modifier-groups/?groups=ClinicalScenario")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        group = data[0]
        assert "group" in group
        assert "description" in group
        assert "modifiers" in group

        # Check modifier structure
        modifier = group["modifiers"][0]
        assert "key" in modifier
        assert "description" in modifier


@pytest.mark.django_db
class TestGraphQLRemoval:
    """Tests verifying GraphQL endpoint is removed."""

    def test_graphql_endpoint_returns_404(self):
        """GraphQL endpoint no longer exists."""
        client = Client()
        response = client.get("/graphql/")

        assert response.status_code == 404

    def test_graphql_post_returns_404(self):
        """GraphQL POST no longer works."""
        client = Client()
        response = client.post(
            "/graphql/",
            data='{"query": "{ __schema { types { name } } }"}',
            content_type="application/json",
        )

        assert response.status_code == 404
