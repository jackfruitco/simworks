"""Tests for simulation API endpoints.

Tests that:
1. List simulations returns user's simulations
2. Get simulation returns correct details
3. Create simulation works with valid data
4. End simulation works for in-progress simulations
5. Authorization checks work correctly
6. Pagination works correctly
"""

from unittest.mock import AsyncMock, patch

from django.test import Client
from django.utils import timezone
import pytest

from api.v1.auth import create_access_token
from tests.helpers.assertions import assert_payload_has_fields, assert_response_status


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
def trainerlab_lab(db):
    from apps.accounts.models import Lab

    lab, _ = Lab.objects.get_or_create(
        slug="trainerlab",
        defaults={"display_name": "TrainerLab", "is_active": True},
    )
    return lab


@pytest.fixture
def instructor_membership(test_user, trainerlab_lab):
    from apps.accounts.models import LabMembership

    return LabMembership.objects.create(
        user=test_user,
        lab=trainerlab_lab,
        access_level=LabMembership.AccessLevel.INSTRUCTOR,
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
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="John Doe",
    )


@pytest.fixture
def chatlab_session(simulation):
    """Attach a ChatSession to the test simulation (makes it ChatLab-backed)."""
    from apps.chatlab.models import ChatSession

    return ChatSession.objects.create(simulation=simulation)


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

    def test_list_simulations_excludes_other_users(self, auth_client, test_user, other_user):
        """Does not return simulations belonging to other users."""
        from apps.simcore.models import Simulation

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

        from apps.simcore.models import Simulation

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
        from apps.simcore.models import Simulation

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

    def test_list_simulations_pagination_stays_stable_for_same_timestamp(
        self,
        auth_client,
        test_user,
    ):
        from apps.simcore.models import Simulation

        simulations = [
            Simulation.objects.create(user=test_user, sim_patient_full_name=f"Patient {i}")
            for i in range(3)
        ]
        shared_timestamp = timezone.now()
        Simulation.objects.filter(pk__in=[sim.pk for sim in simulations]).update(
            start_timestamp=shared_timestamp
        )

        first_page = auth_client.get("/api/v1/simulations/?limit=2")
        assert first_page.status_code == 200
        first_data = first_page.json()
        assert len(first_data["items"]) == 2
        assert first_data["has_more"] is True

        second_page = auth_client.get(
            f"/api/v1/simulations/?limit=2&cursor={first_data['next_cursor']}"
        )
        assert second_page.status_code == 200
        second_data = second_page.json()
        assert len(second_data["items"]) == 1

        seen_ids = [item["id"] for item in first_data["items"]] + [
            item["id"] for item in second_data["items"]
        ]
        assert len(seen_ids) == len(set(seen_ids)) == 3

    def test_list_simulations_supports_search_query(self, auth_client, test_user):
        from apps.simcore.models import Simulation

        Simulation.objects.create(
            user=test_user,
            diagnosis="Pulmonary Embolism",
            sim_patient_full_name="Patient A",
        )
        Simulation.objects.create(
            user=test_user,
            diagnosis="Appendicitis",
            sim_patient_full_name="Patient B",
        )

        response = auth_client.get("/api/v1/simulations/?q=Pulmonary")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["diagnosis"] == "Pulmonary Embolism"

    def test_list_simulations_supports_message_search(self, auth_client, test_user):
        from apps.chatlab.models import Message, RoleChoices
        from apps.simcore.models import Conversation, ConversationType, Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Patient M",
        )
        conversation_type, _ = ConversationType.objects.get_or_create(
            slug="simulated_patient",
            defaults={
                "display_name": "Patient",
                "ai_persona": "patient",
            },
        )
        conversation = Conversation.objects.create(
            simulation=sim,
            conversation_type=conversation_type,
            display_name="Patient",
            display_initials="Pt",
        )
        Message.objects.create(
            simulation=sim,
            conversation=conversation,
            sender=test_user,
            content="unique chest pain phrase",
            role=RoleChoices.USER,
            is_from_ai=False,
        )

        response = auth_client.get(
            "/api/v1/simulations/?q=unique%20chest%20pain&search_messages=true"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == sim.id


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

    def test_get_simulation_other_user_returns_404(self, auth_client, other_user):
        """Simulation belonging to other user returns 404."""
        from apps.simcore.models import Simulation

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
class TestQuickCreateSimulation:
    @patch("apps.chatlab.utils.create_new_simulation", new_callable=AsyncMock)
    def test_quick_create_simulation_success(self, mock_create, auth_client, test_user):
        from apps.simcore.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Quick Patient",
        )
        mock_create.return_value = sim

        response = auth_client.post(
            "/api/v1/simulations/quick-create/",
            data={
                "modifiers": ["night_shift", "limited_resources"],
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == sim.pk
        assert data["user_id"] == test_user.pk
        test_user.refresh_from_db()
        mock_create.assert_awaited_once_with(
            user=test_user,
            account=test_user.active_account,
            modifiers=["night_shift", "limited_resources"],
        )

    @patch("apps.chatlab.utils.create_new_simulation", new_callable=AsyncMock)
    def test_quick_create_enqueue_failure_returns_failed_retryable_payload(
        self, mock_create, auth_client, test_user
    ):
        from apps.chatlab.models import ChatSession
        from apps.simcore.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Quick Patient",
        )
        ChatSession.objects.create(simulation=sim)
        sim.mark_failed(
            reason_code="chatlab_initial_generation_enqueue_failed",
            reason_text="We could not start this simulation. Please try again.",
            retryable=True,
        )
        mock_create.return_value = sim

        response = auth_client.post(
            "/api/v1/simulations/quick-create/",
            data={"modifiers": []},
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "failed"
        assert data["terminal_reason_code"] == "chatlab_initial_generation_enqueue_failed"
        assert (
            data["terminal_reason_text"] == "We could not start this simulation. Please try again."
        )
        assert data["retryable"] is True


@pytest.mark.django_db
class TestEndSimulation:
    """Tests for POST /simulations/{id}/end/."""

    def test_end_simulation_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.post(f"/api/v1/simulations/{simulation.pk}/end/")

        assert response.status_code == 401

    @patch("apps.simcore.models.Simulation.generate_feedback")
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

    @patch("apps.simcore.models.Simulation.generate_feedback")
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
        from apps.simcore.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.post(f"/api/v1/simulations/{other_sim.pk}/end/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestAdjustSimulation:
    def test_adjust_requires_idempotency_key(
        self,
        auth_client,
        simulation,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerSession

        TrainerSession.objects.create(simulation=simulation)
        response = auth_client.post(
            f"/api/v1/trainerlab/simulations/{simulation.pk}/adjust/",
            data={"target": "trend", "direction": "up"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_adjust_is_idempotent_and_emits_to_runtime_state(
        self,
        auth_client,
        simulation,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerCommand, TrainerSession

        session = TrainerSession.objects.create(simulation=simulation)
        first = auth_client.post(
            f"/api/v1/trainerlab/simulations/{simulation.pk}/adjust/",
            data={
                "target": "avpu",
                "direction": "set",
                "avpu_state": "verbal",
                "note": "Downgrade responsiveness",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="adjust-1",
        )
        assert first.status_code == 200

        second = auth_client.post(
            f"/api/v1/trainerlab/simulations/{simulation.pk}/adjust/",
            data={
                "target": "avpu",
                "direction": "set",
                "avpu_state": "verbal",
                "note": "Downgrade responsiveness",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="adjust-1",
        )
        assert second.status_code == 200
        assert second.json()["command_id"] == first.json()["command_id"]
        assert TrainerCommand.objects.filter(idempotency_key="adjust-1").count() == 1

        session.refresh_from_db()
        adjustments = session.runtime_state_json.get("adjustments", [])
        assert len(adjustments) == 1
        assert adjustments[0]["target"] == "avpu"

    def test_adjust_requires_membership(self, auth_client, simulation):
        from apps.trainerlab.models import TrainerSession

        TrainerSession.objects.create(simulation=simulation)
        response = auth_client.post(
            f"/api/v1/trainerlab/simulations/{simulation.pk}/adjust/",
            data={"target": "trend", "direction": "up"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="adjust-no-membership",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestSimulationOutputFormat:
    """Tests for simulation response format."""

    def test_simulation_includes_all_fields(self, auth_client, test_user, failure_artifacts):
        """Response includes all expected fields."""
        from datetime import timedelta

        from apps.simcore.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            diagnosis="Test Diagnosis",
            chief_complaint="Test Complaint",
            sim_patient_full_name="Test Patient",
            time_limit=timedelta(hours=1),
        )

        failure_artifacts.capture_request(method="GET", url=f"/api/v1/simulations/{sim.pk}/")
        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert_response_status(response, 200, failure_artifacts=failure_artifacts)
        data = response.json()
        failure_artifacts.record("payload", data)

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
            "retryable",
        ]
        assert_payload_has_fields(data, expected_fields, failure_artifacts=failure_artifacts)

    def test_simulation_status_values(self, auth_client, test_user):
        """Status field has correct values based on simulation state."""
        from django.utils.timezone import now

        from apps.simcore.models import Simulation

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

    def test_failed_initial_generation_detail_payload_includes_retryable(
        self, auth_client, test_user
    ):
        from apps.chatlab.models import ChatSession
        from apps.simcore.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Retryable Patient",
            initial_retry_count=0,
        )
        ChatSession.objects.create(simulation=sim)
        sim.mark_failed(
            reason_code="chatlab_initial_generation_enqueue_failed",
            reason_text="Initial patient generation failed.",
            retryable=True,
        )

        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["retryable"] is True

    def test_failed_initial_generation_list_payload_includes_non_retryable_after_limit(
        self, auth_client, test_user
    ):
        from apps.chatlab.models import ChatSession
        from apps.simcore.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Exhausted Patient",
            initial_retry_count=2,
        )
        ChatSession.objects.create(simulation=sim)
        sim.mark_failed(
            reason_code="chatlab_initial_generation_provider_timeout",
            reason_text="Initial patient generation failed.",
            retryable=False,
        )

        response = auth_client.get("/api/v1/simulations/")

        assert response.status_code == 200
        item = next(entry for entry in response.json()["items"] if entry["id"] == sim.pk)
        assert item["status"] == "failed"
        assert item["retryable"] is False

    def test_trainerlab_failed_simulation_serializes_retryable_false(self, auth_client, test_user):
        """TrainerLab-backed failed simulation always has retryable=False."""
        from apps.simcore.models import Simulation
        from apps.trainerlab.models import TrainerSession

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Trainer Patient",
            initial_retry_count=0,
        )
        TrainerSession.objects.create(simulation=sim)
        sim.mark_failed(
            reason_code="trainerlab_initial_generation_enqueue_failed",
            reason_text="Could not start.",
            retryable=False,
        )

        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert response.status_code == 200
        assert response.json()["retryable"] is False

    def test_legacy_initial_generation_code_retryable_for_chatlab_backed_simulation(
        self, auth_client, test_user
    ):
        """Legacy unprefixed initial_generation_* codes remain retryable for ChatLab sims."""
        from apps.chatlab.models import ChatSession
        from apps.simcore.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Legacy Patient",
            initial_retry_count=0,
        )
        ChatSession.objects.create(simulation=sim)
        sim.mark_failed(
            reason_code="initial_generation_enqueue_failed",
            reason_text="Legacy failure.",
            retryable=True,
        )

        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert response.status_code == 200
        assert response.json()["retryable"] is True

    def test_legacy_initial_generation_code_not_retryable_for_trainerlab_backed_simulation(
        self, auth_client, test_user
    ):
        """Legacy unprefixed initial_generation_* codes are NOT retryable for TrainerLab sims."""
        from apps.simcore.models import Simulation
        from apps.trainerlab.models import TrainerSession

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Legacy Trainer",
            initial_retry_count=0,
        )
        TrainerSession.objects.create(simulation=sim)
        sim.mark_failed(
            reason_code="initial_generation_enqueue_failed",
            reason_text="Legacy failure.",
            retryable=True,
        )

        response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert response.status_code == 200
        assert response.json()["retryable"] is False


@pytest.mark.django_db
class TestRetryInitialSimulation:
    @patch("api.v1.endpoints.simulations._enqueue_initial_response")
    def test_retry_initial_success_returns_in_progress_with_null_retryable(
        self, mock_enqueue, auth_client, test_user
    ):
        from apps.chatlab.models import ChatSession
        from apps.simcore.models import ConversationType, Simulation

        mock_enqueue.return_value = "call-123"
        ConversationType.objects.get(slug="simulated_patient")

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Retry Me",
            status=Simulation.SimulationStatus.FAILED,
            initial_retry_count=0,
            terminal_reason_code="chatlab_initial_generation_enqueue_failed",
            terminal_reason_text="Initial patient generation failed.",
            terminal_at=timezone.now(),
            end_timestamp=timezone.now(),
        )
        ChatSession.objects.create(simulation=sim)

        response = auth_client.post(f"/api/v1/simulations/{sim.pk}/retry-initial/")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["retryable"] is None

    @patch("api.v1.endpoints.simulations._enqueue_initial_response")
    def test_retry_initial_enqueue_failure_exhausts_retries_and_sets_retryable_false(
        self, mock_enqueue, auth_client, test_user
    ):
        from apps.chatlab.models import ChatSession
        from apps.simcore.models import Simulation

        mock_enqueue.return_value = None
        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Retry Me",
            status=Simulation.SimulationStatus.FAILED,
            initial_retry_count=1,
            terminal_reason_code="chatlab_initial_generation_provider_timeout",
            terminal_reason_text="Initial patient generation failed.",
            terminal_at=timezone.now(),
            end_timestamp=timezone.now(),
        )
        ChatSession.objects.create(simulation=sim)

        response = auth_client.post(f"/api/v1/simulations/{sim.pk}/retry-initial/")

        assert response.status_code == 500

        detail_response = auth_client.get(f"/api/v1/simulations/{sim.pk}/")
        assert detail_response.status_code == 200
        data = detail_response.json()
        assert data["status"] == "failed"
        assert data["terminal_reason_code"] == "chatlab_initial_generation_enqueue_failed"
        assert data["retryable"] is False

    def test_retry_initial_rejects_trainerlab_simulation_with_400(self, auth_client, test_user):
        """retry-initial/ returns 400 for a TrainerLab-backed simulation."""
        from apps.simcore.models import Simulation
        from apps.trainerlab.models import TrainerSession

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Trainer Patient",
            status=Simulation.SimulationStatus.FAILED,
            terminal_reason_code="trainerlab_initial_generation_enqueue_failed",
            terminal_at=timezone.now(),
            end_timestamp=timezone.now(),
        )
        TrainerSession.objects.create(simulation=sim)

        response = auth_client.post(f"/api/v1/simulations/{sim.pk}/retry-initial/")
        assert response.status_code == 400
