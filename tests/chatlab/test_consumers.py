"""Contract tests for the ChatLab v1 WebSocket consumer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
import pytest

from apps.chatlab import realtime as chat_realtime
from apps.chatlab.consumers import ChatConsumer
from apps.common.models import OutboxEvent
from apps.common.outbox import event_types
from apps.common.outbox.event_types import MESSAGE_CREATED, SIMULATION_STATUS_UPDATED
from apps.common.outbox.outbox import build_canonical_envelope


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
    async def test_chatlab_replay_registry_matches_canonical_outbox_event_types(self):
        assert frozenset(event_types.canonical_event_types()) == chat_realtime.DURABLE_EVENT_TYPES

    @pytest.mark.asyncio
    async def test_unauthenticated_connect_logs_rejection_reason(self):
        consumer = ChatConsumer()
        consumer.scope = {"user": AnonymousUser(), "path": "/ws/v1/chatlab/"}
        consumer.close = AsyncMock()

        with patch("apps.chatlab.consumers.logger.warning") as mock_warning:
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=4401)
        warning_call = next(
            call
            for call in mock_warning.call_args_list
            if call.args[0] == "chatlab.ws.connect_rejected"
        )
        assert warning_call.kwargs["reason"] == "authentication_required"
        assert warning_call.kwargs["close_code"] == 4401

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
        _simulation, user = await create_simulation_and_user()
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/v1/chatlab/")
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "legacy"})
        response = await receive_json(communicator)
        assert response["event_type"] == "error"
        assert response["payload"]["code"] == "invalid_shape"

        await communicator.disconnect()

    async def test_unknown_inbound_event_type_returns_structured_error(self):
        _simulation, user = await create_simulation_and_user()
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/v1/chatlab/")
        communicator.scope["user"] = user

        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to(
            {
                "event_type": "feedback.created",
                "payload": {},
            }
        )
        response = await receive_json(communicator)
        assert response["event_type"] == "error"
        assert response["payload"]["code"] == "unsupported_event_type"
        assert response["payload"]["details"]["event_type"] == "feedback.created"

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
        with pytest.raises(asyncio.TimeoutError):
            await receive_json(communicator, timeout=0.2)

        observer = await connect_and_hello(simulation, user)
        observer_ready = await receive_json(observer)
        assert observer_ready["event_type"] == "session.ready"
        await receive_json(observer)

        typing_started = await receive_json(observer)
        assert typing_started["event_type"] == "typing.started"
        assert typing_started["payload"]["conversation_id"] == 123
        assert typing_started["payload"]["actor_type"] == "user"
        assert typing_started["payload"]["sender_id"] == user.id
        assert typing_started["payload"]["actor_user_id"] == user.id
        expected_uuid = str(user.uuid) if getattr(user, "uuid", None) else None
        assert typing_started["payload"]["actor_user_uuid"] == expected_uuid
        assert typing_started["payload"]["user"] == user.email
        assert "display_initials" in typing_started["payload"]

        await communicator.send_json_to(
            {
                "event_type": "typing.stopped",
                "payload": {"conversation_id": 123},
            }
        )
        typing_stopped = await receive_json(observer)
        assert typing_stopped["event_type"] == "typing.stopped"
        assert typing_stopped["payload"]["conversation_id"] == 123

        await communicator.disconnect()
        await observer.disconnect()

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

    async def test_non_replayable_last_event_id_requires_resync(self):
        simulation, user = await create_simulation_and_user()
        non_replayable = await OutboxEvent.objects.acreate(
            event_type="typing.started",
            simulation_id=simulation.id,
            payload={"conversation_id": 123},
            idempotency_key=f"resume-non-replayable:{uuid4()}",
        )
        communicator = await connect_and_resume(
            simulation,
            user,
            last_event_id=str(non_replayable.id),
        )

        response = await receive_json(communicator)
        assert response["event_type"] == "session.resync_required"
        assert response["payload"]["reason"] == "unknown_last_event_id"

        await communicator.disconnect()


    async def test_chatlab_transient_suppresses_self_user_typing(self):
        simulation, user = await create_simulation_and_user(in_progress=True)
        consumer = ChatConsumer()
        consumer.scope = {"user": user}
        consumer.simulation_id = simulation.id
        consumer.channel_name = "test-channel"
        consumer._send_envelope = AsyncMock()

        envelope = chat_realtime.build_realtime_envelope(
            chat_realtime.TYPING_STARTED,
            {
                "conversation_id": 123,
                "actor_type": "user",
                "sender_id": user.id,
                "actor_user_id": user.id,
                "actor_user_uuid": str(getattr(user, "uuid", "")) if getattr(user, "uuid", None) else None,
                "user": user.email,
                "display_initials": "TU",
            },
        )

        await consumer.chatlab_transient({"event": envelope})

        consumer._send_envelope.assert_not_awaited()

    async def test_chatlab_transient_allows_system_typing(self):
        simulation, user = await create_simulation_and_user(in_progress=True)
        consumer = ChatConsumer()
        consumer.scope = {"user": user}
        consumer.simulation_id = simulation.id
        consumer.channel_name = "test-channel"
        consumer._send_envelope = AsyncMock()

        envelope = chat_realtime.build_realtime_envelope(
            chat_realtime.TYPING_STARTED,
            {
                "conversation_id": None,
                "actor_type": "system",
                "sender_id": None,
                "actor_user_id": None,
                "actor_user_uuid": None,
                "user": "system@medsim.local",
                "display_initials": "TP",
            },
        )

        await consumer.chatlab_transient({"event": envelope})

        consumer._send_envelope.assert_awaited_once()

    async def test_chatlab_transient_non_typing_events_unchanged(self):
        simulation, user = await create_simulation_and_user(in_progress=True)
        consumer = ChatConsumer()
        consumer.scope = {"user": user}
        consumer.simulation_id = simulation.id
        consumer.channel_name = "test-channel"
        consumer._send_envelope = AsyncMock()

        envelope = chat_realtime.build_realtime_envelope(chat_realtime.PING, {"ok": True})
        await consumer.chatlab_transient({"event": envelope})

        consumer._send_envelope.assert_not_awaited()

    async def test_resume_deduplicates_live_events_buffered_during_replay(self, monkeypatch):
        simulation, user = await create_simulation_and_user()
        anchor = await OutboxEvent.objects.acreate(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.id,
            payload={"status": "running", "phase": "warmup"},
            idempotency_key=f"resume-anchor:{uuid4()}",
            correlation_id="corr-anchor",
        )
        replayed = await OutboxEvent.objects.acreate(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.id,
            payload={"status": "completed", "phase": "done"},
            idempotency_key=f"resume-replayed:{uuid4()}",
            correlation_id="corr-replayed",
        )

        consumer = ChatConsumer()
        consumer.scope = {"user": user, "headers": [], "scheme": "http"}
        consumer.simulation_id = simulation.id
        consumer.simulation = simulation
        consumer.room_group_name = f"simulation_{simulation.id}"

        sent_envelopes: list[dict] = []

        async def capture_send(envelope):
            sent_envelopes.append(envelope)

        consumer._send_envelope = capture_send

        async def fake_get_events_after_event(*, simulation_id: int, last_event_id):
            await consumer.outbox_event(
                {
                    "type": "outbox.event",
                    "event": build_canonical_envelope(replayed),
                }
            )
            return [replayed]

        monkeypatch.setattr(
            "apps.chatlab.consumers.get_events_after_event", fake_get_events_after_event
        )

        replay_ok, replay_count = await consumer._replay_after_event_id(
            last_event_id=str(anchor.id),
            correlation_id="corr-resume",
            event_type="session.resume",
        )

        assert replay_ok is True
        assert replay_count == 1
        assert [envelope["event_id"] for envelope in sent_envelopes] == [str(replayed.id)]

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

    async def test_pre_resolved_scope_account_used_for_access(self):
        """When scope['account'] is pre-set by middleware, consumer uses it."""
        from asgiref.sync import sync_to_async

        from apps.accounts.services import get_default_account_for_user

        simulation, user = await create_simulation_and_user()
        account = await sync_to_async(get_default_account_for_user)(user)

        # Link simulation to account
        simulation.account = account
        await simulation.asave(update_fields=["account"])

        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            "/ws/v1/chatlab/",
        )
        communicator.scope["user"] = user
        communicator.scope["account"] = account

        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to(
            {
                "event_type": "session.hello",
                "payload": {"simulation_id": simulation.id},
            }
        )
        response = await receive_json(communicator)
        assert response["event_type"] == "session.ready"
        assert response["payload"]["simulation_id"] == simulation.id

        await communicator.disconnect()
