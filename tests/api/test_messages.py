"""Tests for message API endpoints.

Tests that:
1. List messages returns messages for a simulation
2. Create message works for in-progress simulations
3. Get message returns specific message
4. Authorization checks work correctly
5. Cursor-based pagination works correctly (pk-based cursors)
6. Conversation filtering works correctly
7. Per-conversation locking blocks patient messages after sim ends
"""

from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import Client
import pytest

from api.v1.auth import create_access_token
from tests.helpers.assertions import assert_payload_has_fields, assert_response_status


def _attach_chatlab_session(simulation):
    from apps.chatlab.models import ChatSession

    ChatSession.objects.get_or_create(simulation=simulation)
    return simulation


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

    conversation_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient",
        defaults={
            "display_name": "Patient",
            "ai_persona": "patient",
        },
    )
    return conversation_type


@pytest.fixture
def feedback_type(db):
    """Create a feedback conversation type (Stitch)."""
    from apps.simcore.models import ConversationType

    conversation_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_feedback",
        defaults={
            "display_name": "Stitch",
            "ai_persona": "stitch",
            "locks_with_simulation": False,
        },
    )
    return conversation_type


@pytest.fixture
def simulation(test_user):
    """Create a test simulation."""
    from apps.simcore.models import Simulation

    simulation = Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="John Doe",
    )
    return _attach_chatlab_session(simulation)


@pytest.fixture
def conversation(simulation, patient_type):
    """Create a patient conversation for the test simulation."""
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=patient_type,
        display_name="John Doe",
        display_initials="JD",
    )


@pytest.fixture
def feedback_conversation(simulation, feedback_type):
    """Create a feedback/Stitch conversation for the test simulation."""
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=feedback_type,
        display_name="Stitch",
        display_initials="St",
    )


@pytest.fixture
def message(simulation, conversation, test_user):
    """Create a test message."""
    from apps.chatlab.models import Message, RoleChoices

    return Message.objects.create(
        simulation=simulation,
        conversation=conversation,
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

    def test_list_messages_other_user_simulation_returns_404(self, auth_client, other_user):
        """Simulation belonging to other user returns 404."""
        from apps.simcore.models import Simulation

        other_sim = Simulation.objects.create(
            user=other_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.get(f"/api/v1/simulations/{other_sim.pk}/messages/")

        assert response.status_code == 404

    def test_list_messages_excludes_deleted(self, auth_client, simulation, conversation, test_user):
        """Deleted messages are not returned."""
        from apps.chatlab.models import Message, RoleChoices

        Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Deleted message",
            role=RoleChoices.USER,
            is_deleted=True,
        )

        visible_msg = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Visible message",
            role=RoleChoices.USER,
            is_deleted=False,
        )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/")
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == visible_msg.pk

    def test_list_messages_ordering_asc(self, auth_client, simulation, conversation, test_user):
        """Messages are ordered ascending (by pk) by default."""
        from apps.chatlab.models import Message, RoleChoices

        for i in range(3):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?order=asc")
        data = response.json()

        ids = [item["id"] for item in data["items"]]
        assert ids == sorted(ids)

    def test_list_messages_ordering_desc(self, auth_client, simulation, conversation, test_user):
        """Messages can be ordered descending."""
        from apps.chatlab.models import Message, RoleChoices

        for i in range(3):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?order=desc")
        data = response.json()

        ids = [item["id"] for item in data["items"]]
        assert ids == sorted(ids, reverse=True)

    def test_list_messages_includes_conversation_type(
        self, auth_client, simulation, conversation, message
    ):
        """Messages include conversation_type from select_related."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/")
        data = response.json()

        assert data["items"][0]["conversation_type"] == "simulated_patient"
        assert data["items"][0]["conversation_id"] == conversation.pk

    def test_list_messages_includes_media_list_with_absolute_urls(
        self, auth_client, simulation, conversation, test_user
    ):
        """List responses expose canonical media metadata with absolute URLs."""
        from io import BytesIO

        from PIL import Image

        from apps.chatlab.models import Message, MessageMediaLink, RoleChoices
        from apps.simcore.models import SimulationImage

        msg = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="See attached image",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
            message_type=Message.MessageType.IMAGE,
            display_name="Patient",
        )

        buffer = BytesIO()
        Image.new("RGB", (24, 24), color=(10, 120, 200)).save(buffer, format="PNG")
        media = SimulationImage(
            simulation=simulation,
            description="wrist image",
            mime_type="image/png",
        )
        media.original.save("wrist-list.png", ContentFile(buffer.getvalue()), save=False)
        media.save()
        MessageMediaLink.objects.create(message=msg, media=media)

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/")
        assert response.status_code == 200
        data = response.json()

        item = data["items"][0]
        assert "media_list" in item
        assert len(item["media_list"]) == 1
        assert item["media_list"][0]["original_url"].startswith("http://testserver/")
        assert item["media_list"][0]["thumbnail_url"].startswith("http://testserver/")

    def test_list_messages_filter_by_conversation(
        self, auth_client, simulation, conversation, feedback_conversation, test_user
    ):
        """conversation_id query param filters messages to that conversation."""
        from apps.chatlab.models import Message, RoleChoices

        patient_msg = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Patient message",
            role=RoleChoices.USER,
        )
        feedback_msg = Message.objects.create(
            simulation=simulation,
            conversation=feedback_conversation,
            sender=test_user,
            content="Feedback message",
            role=RoleChoices.USER,
        )

        # Filter to patient only
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/?conversation_id={conversation.pk}"
        )
        data = response.json()
        ids = [item["id"] for item in data["items"]]
        assert patient_msg.pk in ids
        assert feedback_msg.pk not in ids

        # Filter to feedback only
        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/?conversation_id={feedback_conversation.pk}"
        )
        data = response.json()
        ids = [item["id"] for item in data["items"]]
        assert feedback_msg.pk in ids
        assert patient_msg.pk not in ids


@pytest.mark.django_db
class TestMessagePagination:
    """Tests for cursor-based message pagination."""

    def test_pagination_with_limit(self, auth_client, simulation, conversation, test_user):
        """Pagination respects limit parameter."""
        from apps.chatlab.models import Message, RoleChoices

        for i in range(5):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?limit=2")
        data = response.json()

        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    def test_pagination_cursor_is_pk_based(self, auth_client, simulation, conversation, test_user):
        """Cursor value is the pk of the last message on the page."""
        from apps.chatlab.models import Message, RoleChoices

        for i in range(5):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=test_user,
                content=f"Message {i}",
                role=RoleChoices.USER,
            )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?limit=2")
        data = response.json()

        last_item = data["items"][-1]
        assert data["next_cursor"] == str(last_item["id"])

    def test_pagination_with_cursor(self, auth_client, simulation, conversation, test_user):
        """Cursor-based pagination returns next page without overlap."""
        from apps.chatlab.models import Message, RoleChoices

        for i in range(5):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
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

    def test_pagination_last_page_has_no_cursor(
        self, auth_client, simulation, conversation, test_user
    ):
        """Last page has no next_cursor."""
        from apps.chatlab.models import Message, RoleChoices

        for i in range(2):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
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
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/?cursor=invalid")

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

    @patch("api.v1.endpoints.messages._enqueue_ai_reply")
    def test_create_message_success(
        self, mock_enqueue, auth_client, simulation, conversation, test_user
    ):
        """Creates message and enqueues AI response."""
        mock_enqueue.return_value = "test-call-id"

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Hello, patient!"},
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["content"] == "Hello, patient!"
        assert data["simulation_id"] == simulation.pk
        assert data["sender_id"] == test_user.pk
        assert data["role"] == "user"
        assert data["is_from_ai"] is False
        assert data["conversation_id"] == conversation.pk
        assert data["conversation_type"] == "simulated_patient"
        assert data["media_list"] == []

    def test_create_message_simulation_not_found_returns_404(self, auth_client):
        """Non-existent simulation returns 404."""
        response = auth_client.post(
            "/api/v1/simulations/99999/messages/",
            data={"content": "Test"},
            content_type="application/json",
        )

        assert response.status_code == 404

    @patch("apps.simcore.models.Simulation.generate_feedback")
    def test_create_message_locked_patient_conversation_returns_400(
        self, mock_feedback, auth_client, simulation, conversation
    ):
        """Cannot create message in locked patient conversation after sim ends."""
        simulation.end()

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Test"},
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("apps.simcore.models.Simulation.generate_feedback")
    @patch("api.v1.endpoints.messages._enqueue_ai_reply")
    def test_create_message_stitch_conversation_after_lock_succeeds(
        self, mock_enqueue, mock_feedback, auth_client, simulation, feedback_conversation
    ):
        """Can create message in Stitch/feedback conversation after sim ends."""
        mock_enqueue.return_value = "test-call-id"
        simulation.end()

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={
                "content": "Tell me about my performance",
                "conversation_id": feedback_conversation.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["conversation_id"] == feedback_conversation.pk
        assert data["conversation_type"] == "simulated_feedback"

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

    def test_create_message_other_user_simulation_returns_404(self, auth_client, other_user):
        """Cannot create message in other user's simulation."""
        from apps.simcore.models import Simulation

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

    @pytest.mark.django_db(transaction=True)
    @patch("api.v1.endpoints.messages._enqueue_ai_reply")
    def test_create_message_enqueue_failure_still_returns_202_and_marks_message_failed(
        self, mock_enqueue, auth_client, simulation, conversation
    ):
        """Immediate enqueue failure returns the failed delivery state in the 202 body."""
        from apps.chatlab.models import Message
        from apps.common.models import OutboxEvent

        mock_enqueue.return_value = None

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "Test message"},
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["delivery_status"] == Message.DeliveryStatus.FAILED
        assert data["delivery_error_code"] == "enqueue_failed"
        assert (
            data["delivery_error_text"]
            == "Message queued locally but failed to start AI processing. Try again."
        )
        assert data["delivery_retryable"] is True

        msg = Message.objects.get(pk=data["id"])
        assert msg.delivery_status == Message.DeliveryStatus.FAILED
        assert msg.delivery_error_code == "enqueue_failed"
        assert msg.delivery_retryable is True

        status_events = list(
            OutboxEvent.objects.filter(
                event_type="message.delivery.updated",
                simulation_id=simulation.pk,
            ).order_by("created_at")
        )
        assert len(status_events) == 1
        assert status_events[0].payload["id"] == msg.id
        assert status_events[0].payload["status"] == Message.DeliveryStatus.FAILED
        assert status_events[0].payload["retryable"] is True


@pytest.mark.django_db
class TestGetMessage:
    """Tests for GET /simulations/{id}/messages/{message_id}/."""

    def test_get_message_unauthenticated_returns_401(self, simulation, message):
        """Unauthenticated request returns 401."""
        client = Client()
        response = client.get(f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/")

        assert response.status_code == 401

    def test_get_message_success(self, auth_client, simulation, message):
        """Returns message details."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == message.pk
        assert data["content"] == "Test message content"

    def test_get_message_not_found_returns_404(self, auth_client, simulation):
        """Non-existent message returns 404."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/99999/")

        assert response.status_code == 404

    def test_get_message_wrong_simulation_returns_404(self, auth_client, test_user, message):
        """Message from different simulation returns 404."""
        from apps.simcore.models import Simulation

        other_sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Other Patient",
        )

        response = auth_client.get(f"/api/v1/simulations/{other_sim.pk}/messages/{message.pk}/")

        assert response.status_code == 404

    def test_get_deleted_message_returns_404(self, auth_client, simulation, message):
        """Deleted message returns 404."""
        message.is_deleted = True
        message.save()

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestRetryMessage:
    """Tests for POST /simulations/{id}/messages/{message_id}/retry/."""

    @pytest.mark.django_db(transaction=True)
    @patch("api.v1.endpoints.messages._enqueue_ai_reply")
    def test_retry_message_enqueue_failure_returns_failed_delivery_state(
        self, mock_enqueue, auth_client, simulation, conversation, test_user
    ):
        """Immediate retry enqueue failure returns the failed delivery state in the 202 body."""
        from apps.chatlab.models import Message, RoleChoices

        mock_enqueue.return_value = None
        message = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Retry me",
            role=RoleChoices.USER,
            message_type=Message.MessageType.TEXT,
            is_from_ai=False,
            delivery_status=Message.DeliveryStatus.FAILED,
            delivery_retryable=True,
            delivery_retry_count=0,
            delivery_error_code="ai_processing_failed",
            delivery_error_text="Message failed to deliver to the AI service. Try again.",
        )

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/retry/",
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["delivery_status"] == Message.DeliveryStatus.FAILED
        assert data["delivery_error_code"] == "enqueue_failed"
        assert (
            data["delivery_error_text"]
            == "Message queued locally but failed to start AI processing. Try again."
        )
        assert data["delivery_retryable"] is True
        assert data["delivery_retry_count"] == 1

        message.refresh_from_db()
        assert message.delivery_status == Message.DeliveryStatus.FAILED
        assert message.delivery_error_code == "enqueue_failed"
        assert message.delivery_retryable is True
        assert message.delivery_retry_count == 1

    @patch("api.v1.endpoints.messages._enqueue_ai_reply")
    def test_retry_message_returns_media_fields(
        self, mock_enqueue, auth_client, simulation, conversation, test_user
    ):
        """Retry responses keep the same canonical message payload shape."""
        from apps.chatlab.models import Message, RoleChoices

        mock_enqueue.return_value = "retry-call-id"
        message = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Retry me",
            role=RoleChoices.USER,
            message_type=Message.MessageType.TEXT,
            is_from_ai=False,
            delivery_status=Message.DeliveryStatus.FAILED,
            delivery_retryable=True,
            delivery_retry_count=0,
        )

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/retry/",
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["id"] == message.pk
        assert data["media_list"] == []


@pytest.mark.django_db
class TestMessageOutputFormat:
    """Tests for message response format."""

    def test_message_includes_all_fields(self, auth_client, simulation, message, failure_artifacts):
        """Response includes all expected fields."""
        failure_artifacts.capture_request(
            method="GET",
            url=f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/",
        )
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/")
        assert_response_status(response, 200, failure_artifacts=failure_artifacts)
        data = response.json()
        failure_artifacts.record("payload", data)

        expected_fields = [
            "id",
            "simulation_id",
            "conversation_id",
            "conversation_type",
            "sender_id",
            "content",
            "role",
            "message_type",
            "timestamp",
            "is_from_ai",
            "display_name",
        ]
        assert_payload_has_fields(data, expected_fields, failure_artifacts=failure_artifacts)

    def test_message_does_not_include_order_field(self, auth_client, simulation, message):
        """The 'order' field was removed — verify it's not in the response."""
        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/{message.pk}/")
        data = response.json()
        assert "order" not in data

    def test_message_role_mapping(self, auth_client, simulation, conversation, test_user):
        """Role field is mapped correctly."""
        from apps.chatlab.models import Message, RoleChoices

        user_msg = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="User content",
            role=RoleChoices.USER,
        )

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/{user_msg.pk}/")
        assert response.json()["role"] == "user"

        assistant_msg = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Assistant content",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
        )

        response = auth_client.get(
            f"/api/v1/simulations/{simulation.pk}/messages/{assistant_msg.pk}/"
        )
        assert response.json()["role"] == "assistant"

    def test_message_includes_media_list_with_absolute_urls(
        self, auth_client, simulation, conversation, test_user
    ):
        from io import BytesIO

        from PIL import Image

        from apps.chatlab.models import Message, MessageMediaLink, RoleChoices
        from apps.simcore.models import SimulationImage

        msg = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="See attached image",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
            message_type=Message.MessageType.IMAGE,
            display_name="Patient",
        )

        buffer = BytesIO()
        Image.new("RGB", (24, 24), color=(10, 120, 200)).save(buffer, format="PNG")
        media = SimulationImage(
            simulation=simulation,
            description="wrist image",
            mime_type="image/png",
        )
        media.original.save("wrist.png", ContentFile(buffer.getvalue()), save=False)
        media.save()
        MessageMediaLink.objects.create(message=msg, media=media)

        response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/messages/{msg.pk}/")
        assert response.status_code == 200
        data = response.json()

        assert "media_list" in data
        assert len(data["media_list"]) == 1
        item = data["media_list"][0]
        assert item["original_url"].startswith("http://testserver/")
        assert item["thumbnail_url"].startswith("http://testserver/")


@pytest.mark.django_db
class TestGuardDeniedChatSend:
    """Tests that ChatLab send denial returns structured guard_denial.

    Verifies the 403 response carries a typed ``guard_denial`` object
    with the same canonical code and semantics as the guard-state endpoint.
    """

    @patch("apps.guards.services.check_chat_send_allowed")
    def test_locked_usage_returns_structured_guard_denial(
        self, mock_check, auth_client, simulation, conversation
    ):
        """A send on a locked_usage session returns guard_denied with canonical code."""
        from apps.guards.decisions import GuardDecision
        from apps.guards.enums import (
            DenialReason,
            GuardState,
            LabType,
            PauseReason,
        )
        from apps.guards.models import SessionPresence

        SessionPresence.objects.create(
            simulation=simulation,
            lab_type=LabType.CHATLAB,
            guard_state=GuardState.LOCKED_USAGE,
            pause_reason=PauseReason.USAGE_LIMIT,
            engine_runnable=False,
        )
        mock_check.return_value = GuardDecision.deny(
            DenialReason.USAGE_LIMIT_REACHED,
            "Session locked due to usage limits.",
        )

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "hello"},
            content_type="application/json",
        )

        assert response.status_code == 403
        data = response.json()
        assert data["type"] == "guard_denied"

        denial = data.get("guard_denial")
        assert denial is not None, "403 response missing guard_denial object"
        assert denial["code"] == DenialReason.USAGE_LIMIT_REACHED
        assert denial["severity"] == "error"
        assert denial["resumable"] is True
        assert denial["terminal"] is False
        assert denial["metadata"]["guard_state"] == GuardState.LOCKED_USAGE
        assert denial["metadata"]["guard_reason"] == PauseReason.USAGE_LIMIT
        assert "pause_reason" not in denial["metadata"]

    @patch("apps.guards.services.check_chat_send_allowed")
    def test_paused_runtime_cap_returns_terminal_guard_denial(
        self, mock_check, auth_client, simulation, conversation
    ):
        """A send on a runtime-capped session returns terminal denial."""
        from apps.guards.decisions import GuardDecision
        from apps.guards.enums import (
            DenialReason,
            GuardState,
            LabType,
            PauseReason,
        )
        from apps.guards.models import SessionPresence

        SessionPresence.objects.create(
            simulation=simulation,
            lab_type=LabType.CHATLAB,
            guard_state=GuardState.PAUSED_RUNTIME_CAP,
            pause_reason=PauseReason.RUNTIME_CAP,
            engine_runnable=False,
        )
        mock_check.return_value = GuardDecision.deny(
            DenialReason.RUNTIME_CAP_REACHED,
            "Engine progression is no longer available for this session.",
        )

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/messages/",
            data={"content": "hello"},
            content_type="application/json",
        )

        assert response.status_code == 403
        data = response.json()
        assert data["type"] == "guard_denied"

        denial = data["guard_denial"]
        assert denial["code"] == DenialReason.RUNTIME_CAP_REACHED
        assert denial["resumable"] is False
        assert denial["terminal"] is True
