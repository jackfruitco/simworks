"""Tests for simulation tools API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.fixture(autouse=True)
def chatlab_access(test_user):
    """Grant entitlement-based ChatLab access on the user's personal account."""
    from apps.accounts.services import get_personal_account_for_user
    from apps.billing.catalog import ProductCode
    from apps.billing.models import Entitlement

    personal_account = get_personal_account_for_user(test_user)
    return Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:chatlab-go",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=test_user,
        product_code=ProductCode.CHATLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
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
        metadata_tool = next(
            item for item in data["items"] if item["name"] == "simulation_metadata"
        )
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
        assert response.status_code == 422
        assert "submitted_orders" in response.json()["detail"]

    def test_sign_orders_rejects_too_many_orders(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"submitted_orders": [f"Order {index}" for index in range(51)]},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert "at most 50 items" in response.json()["detail"]

    def test_sign_orders_rejects_overlong_order(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"submitted_orders": ["C" * 256]},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert "at most 255 characters" in response.json()["detail"]

    def test_sign_orders_requires_submitted_orders_field(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"orders": ["CBC"]},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert "submitted_orders" in response.json()["detail"]

    @patch("apps.simcore.orca.services.GenerateInitialFeedback.task")
    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_sign_orders_success(
        self,
        mock_lab_results_task,
        mock_feedback_task,
        auth_client,
        simulation,
    ):
        mock_feedback_task.using.side_effect = AssertionError(
            "Feedback generation should not be used for tool lab orders"
        )
        mock_enqueue = MagicMock()
        mock_enqueue.aenqueue = AsyncMock(return_value="call-id-123")
        mock_lab_results_task.using.return_value = mock_enqueue

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"submitted_orders": ["CBC", "CMP"]},
            content_type="application/json",
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["call_id"] == "call-id-123"
        assert data["orders"] == ["CBC", "CMP"]
        mock_lab_results_task.using.assert_called_once()
        assert mock_lab_results_task.using.call_args.kwargs["context"] == {
            "simulation_id": simulation.id,
            "orders": ["CBC", "CMP"],
        }
        assert "lab_orders" not in mock_lab_results_task.using.call_args.kwargs["context"]
        mock_feedback_task.using.assert_not_called()

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_sign_orders_normalizes_orders(self, mock_lab_results_task, auth_client, simulation):
        mock_enqueue = MagicMock()
        mock_enqueue.aenqueue = AsyncMock(return_value="call-id-456")
        mock_lab_results_task.using.return_value = mock_enqueue

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/tools/patient_results/orders/",
            data={"submitted_orders": [" CBC ", "BMP", "CBC", "   "]},
            content_type="application/json",
        )

        assert response.status_code == 202
        assert response.json()["orders"] == ["CBC", "BMP"]
        assert mock_lab_results_task.using.call_args.kwargs["context"]["orders"] == [
            "CBC",
            "BMP",
        ]
