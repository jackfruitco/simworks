"""Tests for chatlab WebSocket consumers.

Tests:
- Connection handling
- chat.message_created event delivery
- simulation.metadata.results_created event delivery
- Event handler routing

Note: These tests use transaction=True for database isolation with async operations.
"""

import asyncio
from uuid import uuid4

from channels.testing import WebsocketCommunicator
import pytest

from apps.chatlab.consumers import ChatConsumer


async def create_simulation_and_user():
    """Create a simulation and user for testing (async helper)."""
    from apps.accounts.models import User, UserRole
    from apps.simcore.models import Simulation

    role, _ = await UserRole.objects.aget_or_create(title="Test")
    user = await User.objects.acreate(
        email=f"test_{uuid4().hex[:8]}@test.com",
        role=role,
    )
    simulation = await Simulation.objects.acreate(
        user=user,
        sim_patient_full_name="Test Patient",
    )
    return simulation, user


class TestChatConsumerConnection:
    """Tests for ChatConsumer connection handling."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_connect_valid_simulation(self):
        """Test successful connection to valid simulation."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Should receive init message
        response = await communicator.receive_json_from()
        assert response["type"] == "init_message"
        assert "sim_display_name" in response
        assert response["new_simulation"] is True  # No messages yet

        await communicator.disconnect()


class TestChatMessageCreatedHandler:
    """Tests for chat_message_created handler behavior."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_chat_message_created_with_content_sends_to_client(self):
        """Test that chat_message_created with content is forwarded to client."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Consume init message
        await communicator.receive_json_from()

        # Wait for group add to complete
        await asyncio.sleep(0.1)

        # Directly call the handler method to test event format
        consumer = ChatConsumer()
        consumer.simulation = simulation

        # Mock the send method
        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Test the handler directly
        await consumer.chat_message_created(
            {
                "type": "chat.message_created",
                "id": 123,
                "role": "A",
                "content": "Test message content",
                "timestamp": "2026-01-16T10:30:00Z",
                "status": "completed",
                "isFromAi": True,
            }
        )

        # Verify the message was sent
        assert len(sent_messages) == 1
        import json

        sent_data = json.loads(sent_messages[0])
        assert sent_data["type"] == "chat.message_created"
        assert sent_data["id"] == 123
        assert sent_data["content"] == "Test message content"

        await communicator.disconnect()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_chat_message_created_without_content_or_media_not_sent(self):
        """Test that chat_message_created without content/media is dropped."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Consume init message
        await communicator.receive_json_from()

        # Test the handler directly with invalid event
        consumer = ChatConsumer()
        consumer.simulation = simulation

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Event without content or media
        await consumer.chat_message_created(
            {
                "type": "chat.message_created",
                "id": 456,
                # No content, no media
            }
        )

        # Verify NO message was sent (content required)
        assert len(sent_messages) == 0

        await communicator.disconnect()


class TestSimulationMetadataResultsCreatedHandler:
    """Tests for simulation_metadata_results_created handler behavior."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_metadata_results_created_forwards_to_client(self):
        """Test that simulation_metadata_results_created events are forwarded."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Consume init message
        await communicator.receive_json_from()

        # Test the handler directly
        consumer = ChatConsumer()
        consumer.simulation = simulation

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Test metadata event
        await consumer.simulation_metadata_results_created(
            {
                "type": "simulation.metadata.results_created",
                "tool": "patient_results",
                "results": [
                    {"key": "patient_name", "value": "John Smith"},
                    {"key": "age", "value": "45"},
                ],
            }
        )

        # Verify the event was forwarded
        assert len(sent_messages) == 1
        import json

        sent_data = json.loads(sent_messages[0])
        assert sent_data["type"] == "simulation.metadata.results_created"
        assert sent_data["tool"] == "patient_results"
        assert len(sent_data["results"]) == 2

        await communicator.disconnect()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_metadata_results_created_minimal_event_forwarded(self):
        """Test that minimal metadata event (for HTMX-get) is forwarded."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Consume init message
        await communicator.receive_json_from()

        # Test the handler directly
        consumer = ChatConsumer()
        consumer.simulation = simulation

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Minimal event - no html (client will use HTMX-get)
        await consumer.simulation_metadata_results_created(
            {
                "type": "simulation.metadata.results_created",
                "tool": "simulation_metadata",
            }
        )

        # Verify the event was forwarded
        assert len(sent_messages) == 1
        import json

        sent_data = json.loads(sent_messages[0])
        assert sent_data["type"] == "simulation.metadata.results_created"
        assert sent_data["tool"] == "simulation_metadata"
        assert "html" not in sent_data

        await communicator.disconnect()


class TestTypingEventHandlers:
    """Tests for typing event handlers."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_user_typing_handler_formats_correctly(self):
        """Test that user_typing events are formatted correctly for client."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Consume init message
        await communicator.receive_json_from()

        # Test the handler directly
        consumer = ChatConsumer()
        consumer.simulation = simulation

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Test typing event
        await consumer.user_typing(
            {
                "type": "user_typing",
                "user": "TestUser",
                "display_initials": "TU",
                "conversation_id": 42,
            }
        )

        # Verify the event was formatted and sent
        assert len(sent_messages) == 1
        import json

        sent_data = json.loads(sent_messages[0])
        assert sent_data["type"] == "typing"
        assert sent_data["display_initials"] == "TU"
        assert sent_data["conversation_id"] == 42

        await communicator.disconnect()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_user_stopped_typing_handler_formats_correctly(self):
        """Test that user_stopped_typing events are formatted correctly."""
        simulation, user = await create_simulation_and_user()

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/simulation/{simulation.id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"simulation_id": simulation.id}}
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        # Consume init message
        await communicator.receive_json_from()

        # Test the handler directly
        consumer = ChatConsumer()
        consumer.simulation = simulation

        sent_messages = []

        async def mock_send(text_data):
            sent_messages.append(text_data)

        consumer.send = mock_send

        # Test stopped typing event
        await consumer.user_stopped_typing(
            {
                "type": "user_stopped_typing",
                "user": "TestUser",
                "conversation_id": 42,
            }
        )

        # Verify the event was formatted and sent
        assert len(sent_messages) == 1
        import json

        sent_data = json.loads(sent_messages[0])
        assert sent_data["type"] == "stopped_typing"
        assert sent_data["user"] == "TestUser"
        assert sent_data["conversation_id"] == 42

        await communicator.disconnect()
