"""Tests for simulation tools API endpoints."""

from unittest.mock import patch

from django.test import Client
import pytest

from api.v1.auth import create_access_token


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Tools")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="toolsuser@example.com",
        role=user_role,
    )


@pytest.fixture
def auth_client(test_user):
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        sim_patient_full_name="Tool Patient",
    )


@pytest.fixture
def simulation_with_metadata(simulation):
    from apps.simcore.models import PatientDemographics, SimulationFeedback

    PatientDemographics.objects.create(
        simulation=simulation,
        key="patient_name",
        value="John Smith",
    )
    PatientDemographics.objects.create(
        simulation=simulation,
        key="age",
        value="45",
    )
    SimulationFeedback.objects.create(
        simulation=simulation,
        key="hotwash_correct_diagnosis",
        value="True",
    )
    SimulationFeedback.objects.create(
        simulation=simulation,
        key="hotwash_patient_experience",
        value="4",
    )
    return simulation


@pytest.mark.django_db
class TestToolEndpoints:
    def test_list_tools_returns_items(self, auth_client, simulation):
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/tools/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) > 0
        assert "name" in data["items"][0]
        assert "checksum" in data["items"][0]

    def test_get_specific_tool(self, auth_client, simulation):
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/tools/patient_history/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "patient_history"
        assert "data" in data

    def test_list_tools_returns_typed_simulation_metadata_items(
        self,
        auth_client,
        simulation_with_metadata,
    ):
        response = auth_client.get(f"/api/v1/simulations/{simulation_with_metadata.pk}/tools/")
        assert response.status_code == 200

        data = response.json()
        metadata_tool = next(item for item in data["items"] if item["name"] == "simulation_metadata")
        assert metadata_tool["data"] == [
            {
                "kind": "patient_demographics",
                "key": "patient_name",
                "value": "John Smith",
                "db_pk": metadata_tool["data"][0]["db_pk"],
            },
            {
                "kind": "patient_demographics",
                "key": "age",
                "value": "45",
                "db_pk": metadata_tool["data"][1]["db_pk"],
            },
        ]
        assert all(isinstance(item["db_pk"], int) for item in metadata_tool["data"])

    def test_get_simulation_metadata_returns_typed_payload(
        self,
        auth_client,
        simulation_with_metadata,
    ):
        response = auth_client.get(
            f"/api/v1/simulations/{simulation_with_metadata.pk}/tools/simulation_metadata/"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "simulation_metadata"
        assert data["data"][0]["kind"] == "patient_demographics"
        assert data["data"][0]["key"] == "patient_name"
        assert data["data"][0]["value"] == "John Smith"
        assert isinstance(data["data"][0]["db_pk"], int)

    def test_get_simulation_feedback_returns_typed_payload(
        self,
        auth_client,
        simulation_with_metadata,
    ):
        response = auth_client.get(
            f"/api/v1/simulations/{simulation_with_metadata.pk}/tools/simulation_feedback/"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "simulation_feedback"
        assert data["data"] == [
            {
                "kind": "simulation_feedback",
                "key": "hotwash_correct_diagnosis",
                "value": True,
                "db_pk": data["data"][0]["db_pk"],
            },
            {
                "kind": "simulation_feedback",
                "key": "hotwash_patient_experience",
                "value": 4,
                "db_pk": data["data"][1]["db_pk"],
            },
        ]
        assert all(isinstance(item["db_pk"], int) for item in data["data"])

    def test_get_unknown_tool_returns_404(self, auth_client, simulation):
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/tools/unknown_tool/")
        assert response.status_code == 404

    def test_sign_orders_requires_items(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"submitted_orders": []},
            content_type="application/json",
        )
        assert response.status_code == 400

    @patch("api.v1.endpoints.tools.async_to_sync")
    def test_sign_orders_success(self, mock_async_to_sync, auth_client, simulation):
        mock_async_to_sync.return_value = lambda: "call-id-123"
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"submitted_orders": ["CBC", "CMP"]},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["orders"] == ["CBC", "CMP"]
