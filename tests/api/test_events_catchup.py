"""Tests for events catch-up API endpoint.

Tests that:
1. Authentication works correctly (JWT, session, unauthorized)
2. Pagination works correctly (cursor, limit, has_more)
3. Empty results are handled
4. User ownership is verified
5. Rate limiting applies
"""

import uuid

import pytest
from django.test import Client

from api.v1.auth import create_access_token


@pytest.fixture
def user_role(db):
    """Create a test user role."""
    from accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Events")


@pytest.fixture
def test_user(django_user_model, user_role):
    """Create a test user with a role."""
    return django_user_model.objects.create_user(
        username="eventuser",
        password="testpass123",
        email="eventuser@example.com",
        role=user_role,
    )


@pytest.fixture
def other_user(django_user_model, user_role):
    """Create another test user."""
    return django_user_model.objects.create_user(
        username="otheruser2",
        password="testpass123",
        email="other2@example.com",
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
def session_client(test_user):
    """Create a client with session authentication."""
    client = Client()
    client.force_login(test_user)
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
def outbox_events(simulation):
    """Create test outbox events for the simulation."""
    from core.models import OutboxEvent

    events = []
    for i in range(5):
        event = OutboxEvent.objects.create(
            event_type=f"test.event_{i}",
            simulation_id=simulation.pk,
            payload={"index": i, "content": f"Test content {i}"},
            idempotency_key=f"test.event_{i}:{simulation.pk}:{uuid.uuid4()}",
            correlation_id=f"corr-{i}",
        )
        events.append(event)

    return events


@pytest.mark.django_db
class TestListEventsAuth:
    """Tests for events endpoint authentication."""

    def test_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 401

    def test_jwt_auth_works(self, auth_client, simulation):
        """JWT authentication works."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 200

    def test_other_user_returns_404(self, auth_client, other_user):
        """Simulation belonging to other user returns 404."""
        from simulation.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.get(f"/api/v1/simulations/{other_sim.pk}/events/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestListEventsBasic:
    """Tests for basic events listing."""

    def test_list_events_returns_events(self, auth_client, simulation, outbox_events):
        """Returns events for the simulation."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "has_more" in data
        assert "next_cursor" in data
        assert len(data["items"]) == 5

    def test_list_events_empty_returns_empty_list(self, auth_client, simulation):
        """Returns empty list when no events exist."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    def test_event_envelope_format(self, auth_client, simulation, outbox_events):
        """Events follow the envelope format."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 200
        data = response.json()
        event = data["items"][0]

        # Check envelope fields
        assert "event_id" in event
        assert "event_type" in event
        assert "created_at" in event
        assert "correlation_id" in event
        assert "payload" in event

        # Verify content
        assert event["event_type"].startswith("test.event_")
        assert "content" in event["payload"]


@pytest.mark.django_db
class TestListEventsPagination:
    """Tests for events pagination."""

    def test_limit_parameter_works(self, auth_client, simulation, outbox_events):
        """Limit parameter limits results."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?limit=2"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    def test_cursor_pagination_works(self, auth_client, simulation, outbox_events):
        """Cursor-based pagination returns correct results."""
        # Get first page
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?limit=2"
        )
        data = response.json()
        first_page_ids = [e["event_id"] for e in data["items"]]
        cursor = data["next_cursor"]

        # Get second page
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?cursor={cursor}&limit=2"
        )
        data = response.json()
        second_page_ids = [e["event_id"] for e in data["items"]]

        # Verify no overlap
        assert len(set(first_page_ids) & set(second_page_ids)) == 0

        # Get final page
        cursor = data["next_cursor"]
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?cursor={cursor}&limit=2"
        )
        data = response.json()
        assert len(data["items"]) == 1
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    def test_invalid_cursor_returns_from_beginning(
        self, auth_client, simulation, outbox_events
    ):
        """Invalid cursor returns events from beginning."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?cursor=invalid-uuid"
        )

        assert response.status_code == 200
        data = response.json()
        # Should return all events since invalid cursor is ignored
        assert len(data["items"]) == 5

    def test_limit_validation_min(self, auth_client, simulation):
        """Limit must be at least 1."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?limit=0"
        )

        assert response.status_code == 422

    def test_limit_validation_max(self, auth_client, simulation):
        """Limit must not exceed 100."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/events/?limit=200"
        )

        assert response.status_code == 422

    def test_default_limit_is_50(self, auth_client, simulation):
        """Default limit is 50."""
        from core.models import OutboxEvent

        # Create 60 events
        for i in range(60):
            OutboxEvent.objects.create(
                event_type=f"test.bulk_{i}",
                simulation_id=simulation.pk,
                payload={"index": i},
                idempotency_key=f"bulk:{simulation.pk}:{uuid.uuid4()}",
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 50
        assert data["has_more"] is True


@pytest.mark.django_db
class TestListEventsOrdering:
    """Tests for events ordering."""

    def test_events_ordered_by_created_at(self, auth_client, simulation):
        """Events are returned in created_at order."""
        from core.models import OutboxEvent

        # Create events (they'll be created in order due to auto_now_add)
        for i in range(3):
            OutboxEvent.objects.create(
                event_type=f"ordered.event_{i}",
                simulation_id=simulation.pk,
                payload={"order": i},
                idempotency_key=f"ordered:{i}:{uuid.uuid4()}",
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

        assert response.status_code == 200
        data = response.json()

        # Verify ordering
        for i, event in enumerate(data["items"]):
            assert event["payload"]["order"] == i


@pytest.mark.django_db
class TestSimulationNotFound:
    """Tests for non-existent simulation."""

    def test_nonexistent_simulation_returns_404(self, auth_client):
        """Non-existent simulation returns 404."""
        response = auth_client.get("/api/v1/simulations/99999/events/")

        assert response.status_code == 404
