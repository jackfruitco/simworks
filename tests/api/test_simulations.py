"""Tests for simulation API endpoints.

Tests that:
1. List simulations returns user's simulations
2. Get simulation returns correct details
3. Create simulation works with valid data
4. End simulation works for in-progress simulations
5. Authorization checks work correctly
6. Pagination works correctly
"""

from unittest.mock import patch

import pytest
from django.test import Client

from api.v1.auth import create_access_token


@pytest.fixture
def user_role(db):
    """Create a test user role."""
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Simulations")


@pytest.fixture
def test_user(django_user_model, user_role):
    """Create a test user with a role."""
    return django_user_model.objects.create_user(
        password="testpass123",
        email="simuser@example.com",
        role=user_role,
    )


@pytest.fixture
def other_user(django_user_model, user_role):
    """Create another test user."""
    return django_user_model.objects.create_user(
        password="testpass123",
        email="other@example.com",
        role=user_role,
    )


@pytest.fixture
def auth_client(test_user):
    """Create a client with JWT authentication."""
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def simulation(test_user):
    """Create a test simulation."""
    from simulation.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="John Doe",
    )


@pytest.mark.django_db
class TestListSimulations:
    """Tests for GET /simulations/."""

    def test_list_simulations_unauthenticated_returns_401(self):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get("/api/v1/simulations/")

        assert response.status_code == 401

    def test_list_simulations_returns_user_simulations(self, auth_client, simulation):
        """Returns simulations for the authenticated user."""
        response = auth_client.get("/api/v1/simulations/")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "has_more" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == simulation.pk
        assert data["has_more"] is False

    def test_list_simulations_excludes_other_users(
        self, auth_client, test_user, other_user
    ):
        """Does not return simulations belonging to other users."""
        from simulation.models import Simulation

        # Create simulation for other user
        Simulation.objects.create(
            user=other_user,
            diagnosis="Other Diagnosis",
            chief_complaint="Other Complaint",
            sim_patient_full_name="Jane Doe",
        )

        response = auth_client.get("/api/v1/simulations/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0  # No simulations for test_user

    def test_list_simulations_with_status_filter(self, auth_client, test_user):
        """Can filter by status."""
        from django.utils.timezone import now
        from simulation.models import Simulation

        # Create an in-progress and completed simulation
        Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Active Patient",
        )
        Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Done Patient",
            end_timestamp=now(),
        )

        # Filter for in_progress
        response = auth_client.get("/api/v1/simulations/?status=in_progress")
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "in_progress"

        # Filter for completed
        response = auth_client.get("/api/v1/simulations/?status=completed")
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "completed"

    def test_list_simulations_pagination(self, auth_client, test_user):
        """Pagination with limit and cursor works."""
        from simulation.models import Simulation

        # Create 5 simulations
        sims = []
        for i in range(5):
            sim = Simulation.objects.create(
                user=test_user,
                sim_patient_full_name=f"Patient {i}",
            )
            sims.append(sim)

        # Get first page with limit=2
        response = auth_client.get("/api/v1/simulations/?limit=2")
        data = response.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

        # Use the provided next_cursor for next page
        cursor = data["next_cursor"]
        response = auth_client.get(f"/api/v1/simulations/?limit=2&cursor={cursor}")
        data = response.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True

        # Get final page
        cursor = data["next_cursor"]
        response = auth_client.get(f"/api/v1/simulations/?limit=2&cursor={cursor}")
        data = response.json()
        assert len(data["items"]) == 1
        assert data["has_more"] is False
        assert data["next_cursor"] is None


@pytest.mark.django_db
class TestGetSimulation:
    """Tests for GET /simulations/{id}/."""

    def test_get_simulation_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get(f"/api/v1/simulations/{simulation.pk}/")

        assert response.status_code == 401

    def test_get_simulation_returns_details(self, auth_client, simulation):
        """Returns simulation details."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == simulation.pk
        assert data["diagnosis"] == "Test Diagnosis"
        assert data["chief_complaint"] == "Test Complaint"
        assert data["status"] == "in_progress"

    def test_get_simulation_not_found_returns_404(self, auth_client):
        """Non-existent simulation returns 404."""
        response = auth_client.get("/api/v1/simulations/99999/")

        assert response.status_code == 404

    def test_get_simulation_other_user_returns_404(
        self, auth_client, other_user
    ):
        """Simulation belonging to other user returns 404."""
        from simulation.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.get(f"/api/v1/simulations/{other_sim.pk}/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestCreateSimulation:
    """Tests for POST /simulations/."""

    def test_create_simulation_unauthenticated_returns_401(self):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.post(
            "/api/v1/simulations/",
            data={
                "patient_full_name": "Test Patient",
            },
            content_type="application/json",
        )

        assert response.status_code == 401

    def test_create_simulation_success(self, auth_client, test_user):
        """Creates simulation with valid data."""
        response = auth_client.post(
            "/api/v1/simulations/",
            data={
                "patient_full_name": "New Patient",
                "diagnosis": "New Diagnosis",
                "chief_complaint": "New Complaint",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["diagnosis"] == "New Diagnosis"
        assert data["chief_complaint"] == "New Complaint"
        assert data["status"] == "in_progress"
        assert data["user_id"] == test_user.pk

    def test_create_simulation_with_time_limit(self, auth_client):
        """Creates simulation with time limit."""
        response = auth_client.post(
            "/api/v1/simulations/",
            data={
                "patient_full_name": "Timed Patient",
                "time_limit_seconds": 3600,  # 1 hour
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["time_limit_seconds"] == 3600

    def test_create_simulation_missing_patient_name_returns_422(self, auth_client):
        """Missing required field returns 422."""
        response = auth_client.post(
            "/api/v1/simulations/",
            data={
                "diagnosis": "Test",
            },
            content_type="application/json",
        )

        assert response.status_code == 422

    def test_create_simulation_invalid_time_limit_returns_422(self, auth_client):
        """Invalid time limit returns 422."""
        response = auth_client.post(
            "/api/v1/simulations/",
            data={
                "patient_full_name": "Test Patient",
                "time_limit_seconds": 30,  # Below minimum of 60
            },
            content_type="application/json",
        )

        assert response.status_code == 422


@pytest.mark.django_db
class TestEndSimulation:
    """Tests for POST /simulations/{id}/end/."""

    def test_end_simulation_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.post(f"/api/v1/simulations/{simulation.pk}/end/")

        assert response.status_code == 401

    @patch("simulation.models.Simulation.generate_feedback")
    def test_end_simulation_success(self, mock_feedback, auth_client, simulation):
        """Ends simulation successfully."""
        response = auth_client.post(f"/api/v1/simulations/{simulation.pk}/end/")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == simulation.pk
        assert data["status"] == "completed"
        assert data["end_timestamp"] is not None

        # Verify in database
        simulation.refresh_from_db()
        assert simulation.is_complete

        # Verify feedback generation was called
        mock_feedback.assert_called_once()

    @patch("simulation.models.Simulation.generate_feedback")
    def test_end_simulation_already_ended_returns_400(self, mock_feedback, auth_client, simulation):
        """Ending already-ended simulation returns 400."""
        # First end
        auth_client.post(f"/api/v1/simulations/{simulation.pk}/end/")

        # Try to end again
        response = auth_client.post(f"/api/v1/simulations/{simulation.pk}/end/")

        assert response.status_code == 400

    def test_end_simulation_not_found_returns_404(self, auth_client):
        """Non-existent simulation returns 404."""
        response = auth_client.post("/api/v1/simulations/99999/end/")

        assert response.status_code == 404

    def test_end_simulation_other_user_returns_404(self, auth_client, other_user):
        """Simulation belonging to other user returns 404."""
        from simulation.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.post(f"/api/v1/simulations/{other_sim.pk}/end/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestSimulationOutputFormat:
    """Tests for simulation response format."""

    def test_simulation_includes_all_fields(self, auth_client, test_user):
        """Response includes all expected fields."""
        from datetime import timedelta

        from simulation.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            diagnosis="Test Diagnosis",
            chief_complaint="Test Complaint",
            sim_patient_full_name="Test Patient",
            time_limit=timedelta(hours=1),
        )

        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        data = response.json()

        # Verify all fields are present
        expected_fields = [
            "id",
            "user_id",
            "start_timestamp",
            "end_timestamp",
            "time_limit_seconds",
            "diagnosis",
            "chief_complaint",
            "patient_display_name",
            "patient_initials",
            "status",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    def test_simulation_status_values(self, auth_client, test_user):
        """Status field has correct values based on simulation state."""
        from django.utils.timezone import now
        from simulation.models import Simulation

        # In-progress
        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Patient",
        )
        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert response.json()["status"] == "in_progress"

        # Completed
        sim.end_timestamp = now()
        sim.save()
        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert response.json()["status"] == "completed"
