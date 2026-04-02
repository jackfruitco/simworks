"""Tests for conversation API endpoints.

Tests that:
1. List conversations returns conversations for a simulation
2. Create conversation works (and is idempotent)
3. Get conversation by UUID works
4. HTTP status codes are correct (200 for existing, 201 for new)
"""

from django.test import Client
import pytest

from api.v1.auth import create_access_token


@pytest.fixture
def user_role(db):
    """Create a test user role."""
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Convs")


@pytest.fixture
def test_user(django_user_model, user_role):
    """Create a test user with a role."""
    return django_user_model.objects.create_user(
        password="testpass123",
        email="convuser@example.com",
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
    """Create a client with JWT authentication."""
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def patient_type(db):
    """Create a patient conversation type."""
    from apps.simcore.models import ConversationType

    conv_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient",
        defaults={
            "display_name": "Simulated Patient",
            "ai_persona": "patient",
            "locks_with_simulation": True,
            "available_in": ["chatlab"],
            "sort_order": 0,
        },
    )
    return conv_type


@pytest.fixture
def feedback_type(db):
    """Create a feedback conversation type (Stitch)."""
    from apps.simcore.models import ConversationType

    conv_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_feedback",
        defaults={
            "display_name": "Simulation Feedback",
            "ai_persona": "stitch",
            "locks_with_simulation": False,
            "available_in": ["chatlab"],
            "sort_order": 10,
        },
    )
    return conv_type


@pytest.fixture
def simulation(test_user):
    """Create a test simulation."""
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="Jane Smith",
    )


@pytest.fixture
def conversation(simulation, patient_type):
    """Create a patient conversation for the test simulation."""
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=patient_type,
        display_name="Jane Smith",
        display_initials="JS",
    )


@pytest.mark.django_db
class TestListConversations:
    """Tests for GET /simulations/{id}/conversations/."""

    def test_simulation_defaults_to_users_active_account(self, test_user):
        """New simulations inherit the user's default account context."""
        from apps.simcore.models import Simulation

        simulation = Simulation.objects.create(
            user=test_user,
            diagnosis="Test Diagnosis",
            chief_complaint="Test Complaint",
        )
        test_user.refresh_from_db()

        assert simulation.account_id == test_user.active_account_id

    def test_list_conversations_returns_conversations(self, auth_client, simulation, conversation):
        """Returns conversations for the simulation."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/conversations/")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == conversation.pk
        assert data["items"][0]["conversation_type"] == "simulated_patient"
        assert data["items"][0]["is_locked"] is False

    def test_list_conversations_unauthenticated_returns_401(self, simulation):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get(f"/api/v1/simulations/{simulation.pk}/conversations/")
        assert response.status_code == 401


@pytest.mark.django_db
class TestCreateConversation:
    """Tests for POST /simulations/{id}/conversations/."""

    def test_create_conversation_success(self, auth_client, simulation, feedback_type):
        """Creates a new conversation and returns 201."""
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/conversations/",
            data={"conversation_type": "simulated_feedback"},
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["conversation_type"] == "simulated_feedback"
        assert data["display_name"] == "Stitch"
        assert data["is_locked"] is False

    def test_create_feedback_conversation_creates_initial_stitch_message(
        self, auth_client, simulation, feedback_type
    ):
        """New feedback conversation gets an initial Stitch greeting message."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent
        from apps.common.outbox.event_types import MESSAGE_CREATED

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/conversations/",
            data={"conversation_type": "simulated_feedback"},
            content_type="application/json",
        )

        assert response.status_code == 201
        conversation_id = response.json()["id"]

        messages = Message.objects.filter(
            simulation=simulation,
            conversation_id=conversation_id,
        )
        assert messages.count() == 1

        greeting = messages.get()
        assert greeting.role == RoleChoices.ASSISTANT
        assert greeting.is_from_ai is True
        assert greeting.display_name == "Stitch"
        assert greeting.content == (
            "Hey, what would you like to discuss? Do you have a specific "
            "question about your performance or this scenario?"
        )

        assert OutboxEvent.objects.filter(
            simulation_id=simulation.pk,
            event_type=MESSAGE_CREATED,
            idempotency_key=f"{MESSAGE_CREATED}:{greeting.id}",
        ).exists()

    def test_create_feedback_conversation_idempotent_does_not_duplicate_greeting(
        self, auth_client, simulation, feedback_type
    ):
        """Idempotent create does not create a second Stitch greeting."""
        from apps.chatlab.models import Message
        from apps.common.models import OutboxEvent
        from apps.common.outbox.event_types import MESSAGE_CREATED

        first = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/conversations/",
            data={"conversation_type": "simulated_feedback"},
            content_type="application/json",
        )
        second = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/conversations/",
            data={"conversation_type": "simulated_feedback"},
            content_type="application/json",
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        conversation_id = first.json()["id"]
        assert (
            Message.objects.filter(
                simulation=simulation,
                conversation_id=conversation_id,
                display_name="Stitch",
            ).count()
            == 1
        )

        greeting = Message.objects.get(
            simulation=simulation,
            conversation_id=conversation_id,
            display_name="Stitch",
        )
        assert (
            OutboxEvent.objects.filter(
                simulation_id=simulation.pk,
                event_type=MESSAGE_CREATED,
                idempotency_key=f"{MESSAGE_CREATED}:{greeting.id}",
            ).count()
            == 1
        )

    def test_create_conversation_idempotent_returns_200(
        self, auth_client, simulation, conversation, patient_type
    ):
        """Creating a conversation that already exists returns 200 (not 201)."""
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/conversations/",
            data={"conversation_type": "simulated_patient"},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conversation.pk

    def test_create_conversation_unknown_type_returns_400(self, auth_client, simulation):
        """Unknown conversation type returns 400."""
        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/conversations/",
            data={"conversation_type": "nonexistent_type"},
            content_type="application/json",
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestGetConversation:
    """Tests for GET /simulations/{id}/conversations/{uuid}/."""

    def test_get_conversation_success(self, auth_client, simulation, conversation):
        """Returns conversation by UUID."""
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/conversations/{conversation.uuid}/"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conversation.pk

    def test_get_conversation_not_found_returns_404(self, auth_client, simulation):
        """Non-existent conversation UUID returns 404."""
        import uuid

        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/conversations/{uuid.uuid4()}/"
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestConversationLocking:
    """Tests for conversation lock state."""

    def test_patient_conversation_locked_after_sim_ends(
        self, auth_client, simulation, conversation
    ):
        """Patient conversation shows is_locked=True after simulation ends."""
        from unittest.mock import patch

        with patch("apps.simcore.models.Simulation.generate_feedback"):
            simulation.end()

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/conversations/")
        data = response.json()

        patient_conv = next(
            c for c in data["items"] if c["conversation_type"] == "simulated_patient"
        )
        assert patient_conv["is_locked"] is True

    def test_feedback_conversation_not_locked_after_sim_ends(
        self, auth_client, simulation, conversation, feedback_type
    ):
        """Feedback/Stitch conversation stays unlocked after simulation ends."""
        from unittest.mock import patch

        from apps.simcore.models import Conversation

        Conversation.objects.create(
            simulation=simulation,
            conversation_type=feedback_type,
            display_name="Stitch",
            display_initials="St",
        )

        with patch("apps.simcore.models.Simulation.generate_feedback"):
            simulation.end()

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/conversations/")
        data = response.json()

        feedback_conv = next(
            c for c in data["items"] if c["conversation_type"] == "simulated_feedback"
        )
        assert feedback_conv["is_locked"] is False
