"""Tests for lab-order submission API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import Client
import pytest

from api.v1.auth import create_access_token


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Lab Orders")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="laborders@example.com",
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
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="Lab Order Patient",
    )


@pytest.mark.django_db
class TestLabOrderEndpoints:
    def test_submit_lab_orders_rejects_empty_list(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": []},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert "orders" in response.json()["detail"]

    def test_submit_lab_orders_rejects_too_many_orders(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": [f"Order {index}" for index in range(51)]},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert "at most 50 items" in response.json()["detail"]

    def test_submit_lab_orders_rejects_overlong_order(self, auth_client, simulation):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": ["C" * 256]},
            content_type="application/json",
        )

        assert response.status_code == 422
        assert "at most 255 characters" in response.json()["detail"]

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_submit_lab_orders_success(self, mock_lab_results_task, auth_client, simulation):
        mock_enqueue = MagicMock()
        mock_enqueue.aenqueue = AsyncMock(return_value="call-id-789")
        mock_lab_results_task.using.return_value = mock_enqueue

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": ["CBC", "CMP"]},
            content_type="application/json",
        )

        assert response.status_code == 202
        assert response.json() == {
            "status": "accepted",
            "call_id": "call-id-789",
            "orders": ["CBC", "CMP"],
        }
        assert mock_lab_results_task.using.call_args.kwargs["context"] == {
            "simulation_id": simulation.id,
            "orders": ["CBC", "CMP"],
        }

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_submit_lab_orders_normalizes_orders(
        self,
        mock_lab_results_task,
        auth_client,
        simulation,
    ):
        mock_enqueue = MagicMock()
        mock_enqueue.aenqueue = AsyncMock(return_value="call-id-790")
        mock_lab_results_task.using.return_value = mock_enqueue

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": [" CBC ", "BMP", "CBC", "   "]},
            content_type="application/json",
        )

        assert response.status_code == 202
        assert response.json()["orders"] == ["CBC", "BMP"]
        assert mock_lab_results_task.using.call_args.kwargs["context"]["orders"] == [
            "CBC",
            "BMP",
        ]

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_submit_lab_orders_requires_in_progress_simulation(
        self,
        mock_lab_results_task,
        auth_client,
        simulation,
    ):
        from apps.simcore.models import Simulation

        simulation.status = Simulation.SimulationStatus.COMPLETED
        simulation.save(update_fields=["status"])

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": ["CBC"]},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Lab orders can only be submitted for in-progress simulations"
        )
        mock_lab_results_task.using.assert_not_called()

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_submit_lab_orders_rejects_all_whitespace_orders(
        self,
        mock_lab_results_task,
        auth_client,
        simulation,
    ):
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/lab-orders/",
            data={"orders": ["   ", "\t"]},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "orders must contain at least one non-empty item"
        mock_lab_results_task.using.assert_not_called()
