"""Contract tests for the ChatLab v1 WebSocket consumer."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.utils import timezone
import pytest

from apps.chatlab.consumers import ChatConsumer
from apps.common.models import OutboxEvent
from apps.common.outbox.event_types import MESSAGE_CREATED, SIMULATION_STATUS_UPDATED


async def create_simulation_and_user(*, in_progress: bool = False):
    from django.contrib.auth import get_user_model

    from apps.accounts.models import UserRole
    from apps.simcore.models import Simulation

    User = get_user_model()
    role, _ = await UserRole.objects.aget_or_create(title="Chat WS Test")
    user = await User.objects.acreate(email=f"chatws_{uuid4().hex[:8]}@test.com", role=role)
    simulation = await Simulation.objects.acreate(
        user=user,
        sim_patient_full_name="Test Patient",
        status=(
            Simulation.SimulationStatus.IN_PROGRESS
            if in_progress
            else Simulation.SimulationStatus.COMPLETED
        ),
        end_timestamp=None if in_progress else timezone.now(),
    )
    return simulation, user


async def connect_and_hello(simulation, user, *, last_event_id: str | None = None):
    communicator = WebsocketCommunicator(
        ChatConsumer.as_asgi(),
        "/ws/v1/chatlab/",
    )
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected is True

    payload = {"simulation_id": simulation.id}
    if last_event_id is not None:
        payload["last_event_id"] = last_event_id

    await communicator.send_json_to(
        {
            "event_type": "session.hello",
            "payload": payload,
        }
    )
    return communicator


async def connect_and_resume(simulation, user, *, last_event_id: str):
    communicator = WebsocketCommunicator(
        ChatConsumer.as_asgi(),
        "/ws/v1/chatlab/",
    )
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.send_json_to(
        {
            "event_type": "session.resume",
            "payload": {
                "simulation_id": simulation.id,
                "last_event_id": last_event_id,
            },
        }
    )
    return communicator


async def receive_json(communicator, timeout: float = 1.0):
    return await asyncio.wait_for(communicator.receive_json_from(), timeout=timeout)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestChatConsumerContract:
    async def test_session_ready_uses_canonical_envelope(self):
        simulation, user = await create_simulation_and_user()
        communicator = await connect_and_hello(simulation, user)

        response = await receive_json(communicator)
        assert set(response.keys()) == {
            "event_id",
            "event_type",
            "created_at",
            "correlation_id",
            "payload",
        }
        assert response["event_type"] == "session.ready"
        assert response["payload"]["simulation_id"] == simulation.id
        assert response["payload"]["patient_display_name"] == simulation.sim_patient_display_name

        await communicator.disconnect()

    async def test_invalid_inbound_payload_returns_structured_error(self):
        simulation, user = await create_simulation_and_user()
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/v1/chatlab/")
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "legacy"})
        response = await receive_json(communicator)
        assert response["event_type"] == "error"
        assert response["payload"]["code"] == "invalid_shape"

        await communicator.disconnect()

    async def test_typing_events_are_live_only_and_enveloped(self):
        simulation, user = await create_simulation_and_user(in_progress=True)
        communicator = await connect_and_hello(simulation, user)

        ready = await receive_json(communicator)
        assert ready["event_type"] == "session.ready"

        initial_typing = await receive_json(communicator)
        assert initial_typing["event_type"] == "typing.started"

        await communicator.send_json_to(
            {
                "event_type": "typing.started",
                "payload": {"conversation_id": 123},
            }
        )
        typing_started = await receive_json(communicator)
        assert typing_started["event_type"] == "typing.started"
        assert typing_started["payload"]["conversation_id"] == 123

        await communicator.send_json_to(
            {
                "event_type": "typing.stopped",
                "payload": {"conversation_id": 123},
            }
        )
        typing_stopped = await receive_json(communicator)
        assert typing_stopped["event_type"] == "typing.stopped"
        assert typing_stopped["payload"]["conversation_id"] == 123

        await communicator.disconnect()

    async def test_resume_replays_durable_events_after_anchor_and_excludes_anchor(self):
        simulation, user = await create_simulation_and_user()
        first = await OutboxEvent.objects.acreate(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.id,
            payload={"status": "running", "phase": "warmup"},
            idempotency_key=f"resume-first:{uuid4()}",
            correlation_id="corr-first",
        )
        second = await OutboxEvent.objects.acreate(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.id,
            payload={"status": "completed", "phase": "done"},
            idempotency_key=f"resume-second:{uuid4()}",
            correlation_id="corr-second",
        )

        communicator = await connect_and_resume(
            simulation,
            user,
            last_event_id=str(first.id),
        )

        replayed = await receive_json(communicator)
        assert replayed["event_type"] == SIMULATION_STATUS_UPDATED
        assert replayed["event_id"] == str(second.id)
        assert replayed["payload"]["phase"] == "done"

        resumed = await receive_json(communicator)
        assert resumed["event_type"] == "session.resumed"
        assert resumed["payload"]["replay_count"] == 1

        await communicator.disconnect()

    async def test_unknown_last_event_id_requires_resync(self):
        simulation, user = await create_simulation_and_user()
        communicator = await connect_and_resume(
            simulation,
            user,
            last_event_id=str(uuid4()),
        )

        response = await receive_json(communicator)
        assert response["event_type"] == "session.resync_required"
        assert response["payload"]["reason"] == "unknown_last_event_id"

        await communicator.disconnect()

    async def test_live_durable_event_delivery_uses_canonical_envelope(self):
        simulation, user = await create_simulation_and_user()
        communicator = await connect_and_hello(simulation, user)
        ready = await receive_json(communicator)
        assert ready["event_type"] == "session.ready"

        channel_layer = get_channel_layer()
        assert channel_layer is not None

        durable_event = await OutboxEvent.objects.acreate(
            event_type=MESSAGE_CREATED,
            simulation_id=simulation.id,
            payload={"message_id": 99, "content": "hello"},
            idempotency_key=f"live-durable:{uuid4()}",
            correlation_id="corr-live",
        )
        await channel_layer.group_send(
            f"simulation_{simulation.id}",
            {
                "type": "outbox.event",
                "event": {
                    "event_id": str(durable_event.id),
                    "event_type": MESSAGE_CREATED,
                    "created_at": durable_event.created_at.isoformat(),
                    "correlation_id": "corr-live",
                    "payload": {"message_id": 99, "content": "hello"},
                },
            },
        )

        response = await receive_json(communicator)
        assert response["event_type"] == MESSAGE_CREATED
        assert response["correlation_id"] == "corr-live"
        assert response["payload"]["content"] == "hello"
        assert "media_list" in response["payload"]

        await communicator.disconnect()

    async def test_ping_returns_pong(self):
        simulation, user = await create_simulation_and_user()
        communicator = await connect_and_hello(simulation, user)
        ready = await receive_json(communicator)
        assert ready["event_type"] == "session.ready"

        await communicator.send_json_to(
            {
                "event_type": "ping",
                "correlation_id": "corr-ping",
                "payload": {"client_nonce": "abc123"},
            }
        )
        response = await receive_json(communicator)
        assert response["event_type"] == "pong"
        assert response["correlation_id"] == "corr-ping"
        assert response["payload"]["client_nonce"] == "abc123"

        await communicator.disconnect()

    async def test_access_denied_is_generic_for_other_users(self):
        simulation, _owner = await create_simulation_and_user()
        _other_simulation, other_user = await create_simulation_and_user()

        communicator = await connect_and_hello(simulation, other_user)
        response = await receive_json(communicator)
        assert response["event_type"] == "error"
        assert response["payload"]["code"] == "access_denied"

        await communicator.disconnect()
