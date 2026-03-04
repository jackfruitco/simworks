"""Tests for the message creation and broadcast flow.

Tests the integration between:
1. Message creation signal
2. Outbox event creation
3. WebSocket envelope format
4. Client-side deduplication data
"""

from unittest.mock import patch

import pytest


@pytest.fixture
def user_role(db):
    """Create a test user role."""
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role MessageFlow")


@pytest.fixture
def user(db, user_role):
    """Create a test user."""
    from apps.accounts.models import User

    return User.objects.create_user(
        email="test@example.com",
        password="testpass123",
        role=user_role,
    )


@pytest.fixture
def simulation(db, user):
    """Create a test simulation."""
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="Test Patient",
    )


@pytest.fixture
def patient_type(db):
    from apps.simcore.models import ConversationType

    return ConversationType.objects.get(slug="simulated_patient")


@pytest.fixture
def conversation(db, simulation, patient_type):
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=patient_type,
        display_name="Test Patient",
        display_initials="TP",
    )


@pytest.mark.django_db
class TestMessageBroadcastSignal:
    """Tests for the message broadcast signal handler."""

    def test_non_ai_message_creates_outbox_event(self, simulation, user, conversation):
        """Test that creating a non-AI message creates an outbox event."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent

        # Capture initial outbox count
        initial_count = OutboxEvent.objects.count()

        # Non-AI messages are broadcast by signal as a safety net path.
        with patch("apps.common.outbox.poke_drain_sync"):
            message = Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=user,
                content="Hello doctor.",
                role=RoleChoices.USER,
                is_from_ai=False,
                display_name="Test Patient",
            )

        # Verify outbox event was created
        assert OutboxEvent.objects.count() == initial_count + 1

        # Verify event details
        event = OutboxEvent.objects.latest("created_at")
        assert event.event_type == "chat.message_created"
        assert event.simulation_id == simulation.id
        assert event.idempotency_key == f"chat.message_created:{message.id}"

    def test_user_message_outbox_payload_has_message_id(self, simulation, user, conversation):
        """Test that the outbox payload includes message_id for deduplication."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent

        with patch("apps.common.outbox.poke_drain_sync"):
            message = Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=user,
                content="Test content",
                role=RoleChoices.USER,
                is_from_ai=False,
                display_name="Test Patient",
            )

        event = OutboxEvent.objects.latest("created_at")
        payload = event.payload

        # Verify payload has all required fields for client deduplication
        assert "id" in payload
        assert "message_id" in payload
        assert payload["id"] == message.id
        assert payload["message_id"] == message.id
        assert payload["content"] == "Test content"
        assert payload["isFromAi"] is False
        assert payload["status"] == "sent"

    def test_user_message_creates_outbox_event(self, simulation, user, conversation):
        """Test that user messages create outbox events."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent

        initial_count = OutboxEvent.objects.count()

        # Create a user message (is_from_ai=False)
        Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=user,
            content="Hello doctor",
            role=RoleChoices.USER,
            is_from_ai=False,
        )

        # Verify outbox event was created
        assert OutboxEvent.objects.count() == initial_count + 1
        event = OutboxEvent.objects.latest("created_at")
        assert event.event_type == "chat.message_created"
        assert event.payload["isFromAi"] is False

    def test_duplicate_message_event_is_idempotent(self, simulation, user, conversation):
        """Test that duplicate events are prevented by idempotency key."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent
        from apps.common.outbox import enqueue_event_sync

        with patch("apps.common.outbox.poke_drain_sync"):
            message = Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=user,
                content="Test content",
                role=RoleChoices.USER,
                is_from_ai=False,
            )

        initial_count = OutboxEvent.objects.count()

        # Try to create a duplicate event manually
        result = enqueue_event_sync(
            event_type="chat.message_created",
            simulation_id=simulation.id,
            payload={"id": message.id},
            idempotency_key=f"chat.message_created:{message.id}",
        )

        # Should return None (duplicate)
        assert result is None
        assert OutboxEvent.objects.count() == initial_count


@pytest.mark.django_db
class TestOutboxEnvelopeFormat:
    """Tests for the WebSocket envelope format."""

    def test_build_ws_envelope_has_required_fields(self, simulation):
        """Test that build_ws_envelope creates correct envelope structure."""
        from apps.common.models import OutboxEvent
        from apps.common.outbox import build_ws_envelope

        event = OutboxEvent.objects.create(
            event_type="chat.message_created",
            simulation_id=simulation.id,
            payload={"id": 123, "message_id": 123, "content": "Hello"},
            idempotency_key="test:123",
            correlation_id="corr-123",
        )

        envelope = build_ws_envelope(event)

        # Verify envelope structure
        assert "event_id" in envelope
        assert "event_type" in envelope
        assert "created_at" in envelope
        assert "correlation_id" in envelope
        assert "payload" in envelope

        # Verify values
        assert envelope["event_id"] == str(event.id)
        assert envelope["event_type"] == "chat.message_created"
        assert envelope["correlation_id"] == "corr-123"
        assert envelope["payload"]["id"] == 123
        assert envelope["payload"]["message_id"] == 123

    def test_envelope_event_id_enables_deduplication(self, simulation):
        """Test that each event has a unique event_id for client deduplication."""
        from apps.common.models import OutboxEvent
        from apps.common.outbox import build_ws_envelope

        event1 = OutboxEvent.objects.create(
            event_type="chat.message_created",
            simulation_id=simulation.id,
            payload={"id": 1},
            idempotency_key="test:1",
        )

        event2 = OutboxEvent.objects.create(
            event_type="chat.message_created",
            simulation_id=simulation.id,
            payload={"id": 2},
            idempotency_key="test:2",
        )

        envelope1 = build_ws_envelope(event1)
        envelope2 = build_ws_envelope(event2)

        # Each event should have a unique event_id
        assert envelope1["event_id"] != envelope2["event_id"]


@pytest.mark.django_db
class TestMessagePayloadFormat:
    """Tests for the message payload format sent to clients."""

    def test_payload_matches_client_expectations(self, simulation, user, conversation):
        """Test that payload has all fields expected by chat.js."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent

        with patch("apps.common.outbox.poke_drain_sync"):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=user,
                content="Test message",
                role=RoleChoices.USER,
                is_from_ai=False,
                message_type="text",
                display_name="Dr. Patient",
            )

        event = OutboxEvent.objects.latest("created_at")
        payload = event.payload

        # These fields are used by handleChatMessage in chat.js
        assert "id" in payload  # Used for DOM data-message-id
        assert "message_id" in payload  # Explicit dedup field
        assert "content" in payload  # Message text
        assert "role" in payload  # A or U
        assert "isFromAi" in payload  # For sender detection
        assert "displayName" in payload  # Sender name
        assert "status" in payload  # completed/pending
        assert "messageType" in payload  # chat/feedback

    def test_payload_handles_empty_content(self, simulation, user, conversation):
        """Test that payload handles messages with empty/null content."""
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent

        with patch("apps.common.outbox.poke_drain_sync"):
            Message.objects.create(
                simulation=simulation,
                conversation=conversation,
                sender=user,
                content="",  # Empty content
                role=RoleChoices.USER,
                is_from_ai=False,
            )

        event = OutboxEvent.objects.latest("created_at")
        payload = event.payload

        # Empty content should be empty string, not None
        assert payload["content"] == ""
