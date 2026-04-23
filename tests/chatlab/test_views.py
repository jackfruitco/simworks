"""Tests for chatlab views.

Tests the HTMX endpoints used for real-time message rendering.
"""

from django.test import Client
import pytest


def _attach_chatlab_session(simulation):
    from apps.chatlab.models import ChatSession

    ChatSession.objects.get_or_create(simulation=simulation)
    return simulation


@pytest.fixture
def user_role(db):
    """Create a test user role."""
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Views")


@pytest.fixture
def user(db, user_role):
    """Create a test user."""
    from apps.accounts.models import User

    return User.objects.create_user(
        email="viewtest@example.com",
        password="testpass123",
        role=user_role,
    )


@pytest.fixture
def system_user(db, user_role):
    """Create a system/AI user for AI messages."""
    from apps.accounts.models import User

    return User.objects.create_user(
        email="system@example.com",
        password="systempass123",
        role=user_role,
    )


@pytest.fixture
def simulation(db, user):
    """Create a test simulation."""
    from apps.simcore.models import Simulation

    simulation = Simulation.objects.create(
        user=user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="Test Patient",
    )
    return _attach_chatlab_session(simulation)


@pytest.fixture
def ai_message(db, simulation, system_user, patient_conversation):
    """Create a test AI message from the system user."""
    from apps.chatlab.models import Message, RoleChoices

    return Message.objects.create(
        simulation=simulation,
        conversation=patient_conversation,
        sender=system_user,
        content="Hello, I am your patient.",
        role=RoleChoices.ASSISTANT,
        is_from_ai=True,
        display_name="Test Patient",
    )


@pytest.fixture
def patient_conversation(db, simulation):
    """Create a patient conversation for refresh endpoint tests."""
    from apps.simcore.models import Conversation, ConversationType

    conv_type = ConversationType.objects.create(
        slug="test_simulated_patient",
        display_name="Patient",
        ai_persona="patient",
        locks_with_simulation=True,
    )
    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=conv_type,
        display_name="Patient",
        display_initials="Pt",
    )


@pytest.fixture
def feedback_conversation(db, simulation):
    """Create a second conversation to validate conversation filtering."""
    from apps.simcore.models import Conversation, ConversationType

    conv_type = ConversationType.objects.create(
        slug="test_simulated_feedback",
        display_name="Feedback",
        ai_persona="stitch",
        locks_with_simulation=False,
    )
    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=conv_type,
        display_name="Feedback",
        display_initials="Fb",
    )


@pytest.fixture
def patient_conversation_message(db, simulation, system_user, patient_conversation):
    """Create a message in the patient conversation."""
    from apps.chatlab.models import Message, RoleChoices

    return Message.objects.create(
        simulation=simulation,
        conversation=patient_conversation,
        sender=system_user,
        content="Patient conversation message",
        role=RoleChoices.ASSISTANT,
        is_from_ai=True,
        display_name="Test Patient",
    )


@pytest.fixture
def feedback_conversation_message(db, simulation, system_user, feedback_conversation):
    """Create a message in the feedback conversation."""
    from apps.chatlab.models import Message, RoleChoices

    return Message.objects.create(
        simulation=simulation,
        conversation=feedback_conversation,
        sender=system_user,
        content="Feedback conversation message",
        role=RoleChoices.ASSISTANT,
        is_from_ai=True,
        display_name="Stitch",
    )


@pytest.mark.django_db
class TestChatLabHome:
    def test_index_excludes_trainerlab_backed_simulations(self, client: Client, user):
        from apps.simcore.models import Simulation
        from apps.trainerlab.models import TrainerSession

        chatlab_simulation = Simulation.objects.create(
            user=user,
            sim_patient_full_name="ChatLab Patient",
        )
        _attach_chatlab_session(chatlab_simulation)
        trainerlab_simulation = Simulation.objects.create(
            user=user,
            sim_patient_full_name="TrainerLab Patient",
        )
        TrainerSession.objects.create(simulation=trainerlab_simulation)

        client.force_login(user)
        response = client.get("/chatlab/")

        assert response.status_code == 200
        content = response.content.decode()
        assert f'data-simulation-id="{chatlab_simulation.id}"' in content
        assert f'data-simulation-id="{trainerlab_simulation.id}"' not in content


@pytest.mark.django_db
class TestRefreshMessages:
    """Tests for message refresh HTMX endpoints."""

    def test_refresh_messages_canonical_route_returns_200(
        self, client: Client, user, simulation, patient_conversation_message
    ):
        client.force_login(user)

        response = client.get(
            f"/chatlab/simulation/{simulation.id}/refresh/messages/"
            f"?conversation_id={patient_conversation_message.conversation_id}"
        )

        assert response.status_code == 200
        assert "text/html" in response["Content-Type"]
        assert "Patient conversation message" in response.content.decode()

    def test_refresh_messages_filters_by_conversation_id(
        self,
        client: Client,
        user,
        simulation,
        patient_conversation_message,
        feedback_conversation_message,
    ):
        client.force_login(user)

        response = client.get(
            f"/chatlab/simulation/{simulation.id}/refresh/messages/"
            f"?conversation_id={patient_conversation_message.conversation_id}"
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert "Patient conversation message" in content
        assert "Feedback conversation message" not in content

    def test_refresh_messages_requires_authentication(
        self, client: Client, simulation, patient_conversation_message
    ):
        response = client.get(
            f"/chatlab/simulation/{simulation.id}/refresh/messages/"
            f"?conversation_id={patient_conversation_message.conversation_id}"
        )
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
class TestGetSingleMessage:
    """Tests for the get_single_message HTMX endpoint."""

    def test_returns_404_for_nonexistent_message(self, client: Client, user, simulation):
        """Test that the endpoint returns 404 for a non-existent message."""
        client.force_login(user)

        response = client.get(f"/chatlab/simulation/{simulation.id}/message/99999/")

        assert response.status_code == 404

    def test_returns_200_for_existing_message(self, client: Client, user, simulation, ai_message):
        """Test that the endpoint returns 200 with HTML for an existing message."""
        client.force_login(user)

        response = client.get(f"/chatlab/simulation/{simulation.id}/message/{ai_message.id}/")

        assert response.status_code == 200
        assert "text/html" in response["Content-Type"]

    def test_returns_html_with_message_id_attribute(
        self, client: Client, user, simulation, ai_message
    ):
        """Test that the returned HTML has the data-message-id attribute."""
        client.force_login(user)

        response = client.get(f"/chatlab/simulation/{simulation.id}/message/{ai_message.id}/")

        content = response.content.decode()
        assert f'data-message-id="{ai_message.id}"' in content

    def test_returns_html_with_message_content(self, client: Client, user, simulation, ai_message):
        """Test that the returned HTML contains the message content."""
        client.force_login(user)

        response = client.get(f"/chatlab/simulation/{simulation.id}/message/{ai_message.id}/")

        content = response.content.decode()
        assert "Hello, I am your patient." in content

    def test_requires_authentication(self, client: Client, simulation, ai_message):
        """Test that the endpoint requires authentication."""
        response = client.get(f"/chatlab/simulation/{simulation.id}/message/{ai_message.id}/")

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_renders_ai_message_as_incoming(self, client: Client, user, simulation, ai_message):
        """Test that AI messages are rendered with 'incoming' class (not outgoing)."""
        client.force_login(user)

        response = client.get(f"/chatlab/simulation/{simulation.id}/message/{ai_message.id}/")

        assert response.status_code == 200
        content = response.content.decode()
        # AI messages (is_from_ai=True) should render as incoming
        # because the sender is the AI/system, not the current user viewing
        assert "incoming" in content
        # Should use display_name from the message
        assert "Test Patient" in content

    def test_returns_404_for_wrong_simulation(self, client: Client, user, simulation, ai_message):
        """Test that the endpoint returns 404 if message doesn't belong to simulation."""
        from apps.simcore.models import Simulation

        # Create another simulation
        other_simulation = Simulation.objects.create(
            user=user,
            diagnosis="Other Diagnosis",
            chief_complaint="Other Complaint",
            sim_patient_full_name="Other Patient",
        )
        _attach_chatlab_session(other_simulation)

        client.force_login(user)

        response = client.get(f"/chatlab/simulation/{other_simulation.id}/message/{ai_message.id}/")

        # Should return 404 because message doesn't belong to this simulation
        assert response.status_code == 404
