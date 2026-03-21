"""Tests for WebSocket envelope format standardization.

Tests:
1. Envelope format has required fields
2. ChatConsumer outbox_event handler forwards envelopes
3. NotificationsConsumer outbox_event handler forwards envelopes
4. build_envelope helper generates correct format
5. Invalid envelope (missing event_type) is dropped
"""

from datetime import datetime
import json
import uuid

import pytest

from apps.chatlab.consumers import ChatConsumer
from apps.common.consumers import NotificationsConsumer
from apps.common.outbox import build_ws_envelope


class TestBuildEnvelopeHelper:
    """Tests for ChatConsumer.build_envelope and NotificationsConsumer.build_envelope."""

    def test_build_envelope_has_required_fields(self):
        """Envelope contains all required fields."""
        envelope = ChatConsumer.build_envelope(
            event_type="message.item.created",
            payload={"message_id": 123, "content": "Hello"},
        )

        assert "event_id" in envelope
        assert "event_type" in envelope
        assert "created_at" in envelope
        assert "correlation_id" in envelope
        assert "payload" in envelope

    def test_build_envelope_generates_event_id(self):
        """Event ID is generated if not provided."""
        envelope = ChatConsumer.build_envelope(
            event_type="test.event",
            payload={},
        )

        # Should be a valid UUID
        uuid.UUID(envelope["event_id"])

    def test_build_envelope_uses_provided_event_id(self):
        """Provided event ID is used."""
        custom_id = str(uuid.uuid4())
        envelope = ChatConsumer.build_envelope(
            event_type="test.event",
            payload={},
            event_id=custom_id,
        )

        assert envelope["event_id"] == custom_id

    def test_build_envelope_generates_created_at(self):
        """created_at is generated if not provided."""
        envelope = ChatConsumer.build_envelope(
            event_type="test.event",
            payload={},
        )

        # Should be parseable as ISO format
        datetime.fromisoformat(envelope["created_at"].replace("Z", "+00:00"))

    def test_build_envelope_uses_provided_created_at(self):
        """Provided created_at is used."""
        custom_time = "2024-01-15T10:30:00+00:00"
        envelope = ChatConsumer.build_envelope(
            event_type="test.event",
            payload={},
            created_at=custom_time,
        )

        assert envelope["created_at"] == custom_time

    def test_build_envelope_includes_correlation_id(self):
        """Correlation ID is included in envelope."""
        envelope = ChatConsumer.build_envelope(
            event_type="test.event",
            payload={},
            correlation_id="test-corr-123",
        )

        assert envelope["correlation_id"] == "test-corr-123"

    def test_build_envelope_payload_is_preserved(self):
        """Payload is preserved in envelope."""
        payload = {"key": "value", "nested": {"a": 1}}
        envelope = ChatConsumer.build_envelope(
            event_type="test.event",
            payload=payload,
        )

        assert envelope["payload"] == payload

    def test_notifications_consumer_build_envelope(self):
        """NotificationsConsumer also has build_envelope method."""
        envelope = NotificationsConsumer.build_envelope(
            event_type="notification.created",
            payload={"message": "Hello"},
            correlation_id="corr-456",
        )

        assert envelope["event_type"] == "notification.created"
        assert envelope["payload"] == {"message": "Hello"}
        assert envelope["correlation_id"] == "corr-456"


class TestOutboxBuildWSEnvelope:
    """Tests for core.outbox.build_ws_envelope integration."""

    @pytest.mark.django_db
    def test_outbox_envelope_format_matches_consumer_format(self):
        """Outbox envelope format matches consumer envelope format."""
        from apps.common.models import OutboxEvent

        event = OutboxEvent.objects.create(
            event_type="message.item.created",
            simulation_id=1,
            payload={"message_id": 123},
            idempotency_key="test:1",
            correlation_id="corr-789",
        )

        envelope = build_ws_envelope(event)

        # Should have same structure as build_envelope
        assert "event_id" in envelope
        assert "event_type" in envelope
        assert "created_at" in envelope
        assert "correlation_id" in envelope
        assert "payload" in envelope

        assert envelope["event_type"] == "message.item.created"
        assert envelope["payload"] == {"message_id": 123}
        assert envelope["correlation_id"] == "corr-789"


class TestChatConsumerOutboxEventHandler:
    """Tests for ChatConsumer.outbox_event handler."""

    @pytest.mark.asyncio
    async def test_outbox_event_forwards_envelope_to_client(self):
        """outbox_event handler forwards envelope to WebSocket client."""
        consumer = ChatConsumer()
        consumer.simulation = None  # Not needed for this test

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Simulate outbox event from drain worker
        await consumer.outbox_event(
            {
                "type": "outbox.event",
                "event": {
                    "event_id": "test-event-123",
                    "event_type": "simulation.status.updated",
                    "created_at": "2024-01-15T10:30:00Z",
                    "correlation_id": "corr-123",
                    "payload": {
                        "simulation_id": 456,
                        "status": "completed",
                    },
                },
            }
        )

        assert len(sent_messages) == 1
        sent_data = json.loads(sent_messages[0])

        assert sent_data["event_id"] == "test-event-123"
        assert sent_data["event_type"] == "simulation.status.updated"
        assert sent_data["created_at"] == "2024-01-15T10:30:00Z"
        assert sent_data["correlation_id"] == "corr-123"
        assert sent_data["payload"]["simulation_id"] == 456

    @pytest.mark.asyncio
    async def test_outbox_event_drops_invalid_envelope(self):
        """outbox_event handler drops envelope without event_type."""
        consumer = ChatConsumer()
        consumer.simulation = None

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Invalid envelope - missing event_type
        await consumer.outbox_event(
            {
                "type": "outbox.event",
                "event": {
                    "event_id": "test-event-123",
                    # Missing event_type
                    "payload": {},
                },
            }
        )

        # Should NOT send anything
        assert len(sent_messages) == 0

    @pytest.mark.asyncio
    async def test_outbox_event_handles_empty_event(self):
        """outbox_event handler handles empty event gracefully."""
        consumer = ChatConsumer()
        consumer.simulation = None

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Empty event
        await consumer.outbox_event(
            {
                "type": "outbox.event",
                "event": {},
            }
        )

        # Should NOT send anything
        assert len(sent_messages) == 0


class TestNotificationsConsumerOutboxEventHandler:
    """Tests for NotificationsConsumer.outbox_event handler."""

    @pytest.mark.asyncio
    async def test_outbox_event_forwards_envelope_to_client(self):
        """outbox_event handler forwards envelope to WebSocket client."""
        consumer = NotificationsConsumer()
        consumer.user = type("User", (), {"username": "testuser", "email": "test@example.com"})()

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Simulate outbox event
        await consumer.outbox_event(
            {
                "type": "outbox.event",
                "event": {
                    "event_id": "notif-event-123",
                    "event_type": "simulation.ended",
                    "created_at": "2024-01-15T11:00:00Z",
                    "correlation_id": None,
                    "payload": {
                        "simulation_id": 789,
                        "message": "Simulation ended",
                    },
                },
            }
        )

        assert len(sent_messages) == 1
        sent_data = json.loads(sent_messages[0])

        assert sent_data["event_id"] == "notif-event-123"
        assert sent_data["event_type"] == "simulation.ended"
        assert sent_data["payload"]["simulation_id"] == 789

    @pytest.mark.asyncio
    async def test_outbox_event_drops_invalid_envelope(self):
        """outbox_event handler drops envelope without event_type."""
        consumer = NotificationsConsumer()
        consumer.user = type("User", (), {"username": "testuser", "email": "test@example.com"})()

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Invalid envelope
        await consumer.outbox_event(
            {
                "type": "outbox.event",
                "event": {
                    "event_id": "test-123",
                    # Missing event_type
                },
            }
        )

        assert len(sent_messages) == 0


class TestEnvelopeFormatConsistency:
    """Tests to ensure envelope format is consistent across components."""

    @pytest.mark.django_db
    def test_drain_worker_envelope_matches_expected_format(self):
        """Drain worker produces envelopes that consumers can handle."""
        from apps.common.models import OutboxEvent

        # Create an outbox event
        event = OutboxEvent.objects.create(
            event_type="chat.message_created",
            simulation_id=42,
            payload={
                "id": 100,
                "content": "Test message",
                "role": "A",
                "isFromAi": True,
            },
            idempotency_key="msg:100",
            correlation_id="request-corr-id",
        )

        # Build envelope like drain worker does
        envelope = build_ws_envelope(event)

        # Verify format matches what consumers expect
        assert "event_id" in envelope
        assert "event_type" in envelope
        assert "created_at" in envelope
        assert "correlation_id" in envelope
        assert "payload" in envelope

        # Event ID should be the OutboxEvent UUID
        assert envelope["event_id"] == str(event.id)

        # Event type preserved
        assert envelope["event_type"] == "chat.message_created"

        # Correlation ID preserved
        assert envelope["correlation_id"] == "request-corr-id"

        # Payload preserved
        assert envelope["payload"]["id"] == 100
        assert envelope["payload"]["content"] == "Test message"
