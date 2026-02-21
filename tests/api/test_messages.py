"""Tests for message API endpoints.

Tests that:
1. List messages returns messages for a simulation
2. Create message works for in-progress simulations
3. Get message returns specific message
4. Authorization checks work correctly
5. Cursor-based pagination works correctly
"""

from unittest.mock import patch

import pytest
from django.test import Client

from api.v1.auth import create_access_token


@pytest.fixture
def user_role(db):
    """Create a test user role."""
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Messages")


@pytest.fixture
def test_user(django_user_model, user_role):
    """Create a test user with a role."""
    return django_user_model.objects.create_user(
        password="testpass123",
        email="msguser@example.com",
        role=user_role,
    )


@pytest.fixture
def other_user(django_user_model, user_role):
    """Create another test user."""
    return django_user_model.objects.create_user(
        password="testpass123",
        email="othermsg@example.com",
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


@pytest.fixture
def message(simulation, test_user):
    """Create a test message."""
    from chatlab.models import Message, RoleChoices

    return Message.objects.create(
        simulation=simulation,
        sender=test_user,
        content="Test message content",
        role=RoleChoices.USER,
        message_type="text",
        is_from_ai=False,
    )


@pytest.mark.django_db
class TestListMessages:
    """Tests for GET /simulations/{id}/messages/."""

    def test_list_messages_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get(f"/api/v1/simulations/{simulation.pk}/messages/")

        assert response.status_code == 401

    def test_list_messages_returns_simulation_messages(self, auth_client, simulation, message):
        """Returns messages for the simulation."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "has_more" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == message.pk

    def test_list_messages_simulation_not_found_returns_404(self, auth_client):
        """Non-existent simulation returns 404."""
        response = auth_client.get("/api/v1/simulations/99999/messages/")

        assert response.status_code == 404

    def test_list_messages_other_user_simulation_returns_404(
        self, auth_client, other_user
    ):
        """Simulation belonging to other user returns 404."""
        from simulation.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.get(f"/api/v1/simulations/{other_sim.pk}/messages/")

        assert response.status_code == 404

    def test_list_messages_excludes_deleted(self, auth_client, simulation, test_user):
        """Deleted messages are not returned."""
        from chatlab.models import Message, RoleChoices

        # Create a deleted message
        Message.objects.create(
            simulation=simulation,
            sender=test_user,
            content="Deleted message",
            role=RoleChoices.USER,
            is_deleted=True,
        )

        # Create a non-deleted message
        visible_msg = Message.objects.create(
            simulation=simulation,
            sender=test_user,
            content="Visible message",
            role=RoleChoices.USER,
            is_deleted=False,
        )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/")
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == visible_msg.pk

    def test_list_messages_ordering_asc(self, auth_client, simulation, test_user):
        """Messages are ordered ascending by default."""
        from chatlab.models import Message, RoleChoices

        for i in range(3):
            Message.objects.create(
                simulation=simulation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?order=asc")
        data = response.json()

        # Check order is ascending
        orders = [item["order"] for item in data["items"]]
        assert orders == sorted(orders)

    def test_list_messages_ordering_desc(self, auth_client, simulation, test_user):
        """Messages can be ordered descending."""
        from chatlab.models import Message, RoleChoices

        for i in range(3):
            Message.objects.create(
                simulation=simulation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?order=desc")
        data = response.json()

        # Check order is descending
        orders = [item["order"] for item in data["items"]]
        assert orders == sorted(orders, reverse=True)


@pytest.mark.django_db
class TestMessagePagination:
    """Tests for cursor-based message pagination."""

    def test_pagination_with_limit(self, auth_client, simulation, test_user):
        """Pagination respects limit parameter."""
        from chatlab.models import Message, RoleChoices

        # Create 5 messages
        for i in range(5):
            Message.objects.create(
                simulation=simulation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?limit=2")
        data = response.json()

        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    def test_pagination_with_cursor(self, auth_client, simulation, test_user):
        """Cursor-based pagination returns next page."""
        from chatlab.models import Message, RoleChoices

        # Create 5 messages
        for i in range(5):
            Message.objects.create(
                simulation=simulation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        # Get first page
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?limit=2")
        data = response.json()
        first_page_ids = [item["id"] for item in data["items"]]
        cursor = data["next_cursor"]

        # Get second page
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/?limit=2&cursor={cursor}"
        )
        data = response.json()
        second_page_ids = [item["id"] for item in data["items"]]

        # Verify no overlap
        assert not set(first_page_ids) & set(second_page_ids)

    def test_pagination_last_page_has_no_cursor(self, auth_client, simulation, test_user):
        """Last page has no next_cursor."""
        from chatlab.models import Message, RoleChoices

        # Create 2 messages
        for i in range(2):
            Message.objects.create(
                simulation=simulation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?limit=10")
        data = response.json()

        assert len(data["items"]) == 2
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    def test_pagination_invalid_cursor_returns_400(self, auth_client, simulation):
        """Invalid cursor format returns 400."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/?cursor=invalid"
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestCreateMessage:
    """Tests for POST /simulations/{id}/messages/."""

    def test_create_message_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Test"},
            content_type="application/json",
        )

        assert response.status_code == 401

    @patch("api.v1.endpoints.messages._enqueue_patient_reply")
    def test_create_message_success(self, mock_enqueue, auth_client, simulation, test_user):
        """Creates message and enqueues AI response."""
        mock_enqueue.return_value = "test-call-id"

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Hello, patient!"},
            content_type="application/json",
        )

        # Should return 202 (AI response pending)
        assert response.status_code == 202
        data = response.json()
        assert data["content"] == "Hello, patient!"
        assert data["simulation_id"] == simulation.pk
        assert data["sender_id"] == test_user.pk
        assert data["role"] == "user"
        assert data["is_from_ai"] is False

        # Verify service was enqueued
        mock_enqueue.assert_called_once_with(simulation.pk, data["id"])

    def test_create_message_simulation_not_found_returns_404(self, auth_client):
        """Non-existent simulation returns 404."""
        response = auth_client.post(
            "/api/v1/simulations/99999/messages/",
            data={"content": "Test"},
            content_type="application/json",
        )

        assert response.status_code == 404

    @patch("simulation.models.Simulation.generate_feedback")
    def test_create_message_completed_simulation_returns_400(
        self, mock_feedback, auth_client, simulation
    ):
        """Cannot create message in completed simulation."""
        # End the simulation
        simulation.end()

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Test"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_message_empty_content_returns_422(self, auth_client, simulation):
        """Empty content returns 422."""
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": ""},
            content_type="application/json",
        )

        assert response.status_code == 422

    def test_create_message_missing_content_returns_422(self, auth_client, simulation):
        """Missing content returns 422."""
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={},
            content_type="application/json",
        )

        assert response.status_code == 422

    def test_create_message_other_user_simulation_returns_404(
        self, auth_client, other_user
    ):
        """Cannot create message in other user's simulation."""
        from simulation.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.post(
            f"/api/v1/simulations/{other_sim.pk}/messages/",
            data={"content": "Test"},
            content_type="application/json",
        )

        assert response.status_code == 404

    @patch("api.v1.endpoints.messages._enqueue_patient_reply")
    def test_create_message_enqueue_failure_still_returns_202(
        self, mock_enqueue, auth_client, simulation
    ):
        """Message is created even if service enqueue fails."""
        mock_enqueue.return_value = None  # Simulates enqueue failure

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Test message"},
            content_type="application/json",
        )

        # Message should still be created and 202 returned
        assert response.status_code == 202
        data = response.json()
        assert data["content"] == "Test message"

        # Enqueue was attempted
        mock_enqueue.assert_called_once()


@pytest.mark.django_db
class TestGetMessage:
    """Tests for GET /simulations/{id}/messages/{message_id}/."""

    def test_get_message_unauthenticated_returns_401(self, simulation, message):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/"
        )

        assert response.status_code == 401

    def test_get_message_success(self, auth_client, simulation, message):
        """Returns message details."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == message.pk
        assert data["content"] == "Test message content"

    def test_get_message_not_found_returns_404(self, auth_client, simulation):
        """Non-existent message returns 404."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/99999/"
        )

        assert response.status_code == 404

    def test_get_message_wrong_simulation_returns_404(
        self, auth_client, test_user, message
    ):
        """Message from different simulation returns 404."""
        from simulation.models import Simulation

        other_sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.get(
            f"/api/v1/simulations/{other_sim.pk}/messages/{message.pk}/"
        )

        assert response.status_code == 404

    def test_get_deleted_message_returns_404(self, auth_client, simulation, message):
        """Deleted message returns 404."""
        message.is_deleted = True
        message.save()

        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/"
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestMessageOutputFormat:
    """Tests for message response format."""

    def test_message_includes_all_fields(self, auth_client, simulation, message):
        """Response includes all expected fields."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/"
        )
        data = response.json()

        expected_fields = [
            "id",
            "simulation_id",
            "sender_id",
            "content",
            "role",
            "message_type",
            "timestamp",
            "is_from_ai",
            "order",
            "display_name",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    def test_message_role_mapping(self, auth_client, simulation, test_user):
        """Role field is mapped correctly."""
        from chatlab.models import Message, RoleChoices

        # User message
        user_msg = Message.objects.create(
            simulation=simulation,
            sender=test_user,
            content="User content",
            role=RoleChoices.USER,
        )

        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{user_msg.pk}/"
        )
        assert response.json()["role"] == "user"

        # Assistant message
        assistant_msg = Message.objects.create(
            simulation=simulation,
            sender=test_user,
            content="Assistant content",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
        )

        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{assistant_msg.pk}/"
        )
        assert response.json()["role"] == "assistant"
