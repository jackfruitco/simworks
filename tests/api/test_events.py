"""Tests for catch-up events API."""

from functools import partial
from io import BytesIO
import json

from asgiref.sync import async_to_sync, sync_to_async
from django.core.files.base import ContentFile
from django.test import Client, RequestFactory
from PIL import Image
import pytest

from api.v1.auth import create_access_token
from api.v1.sse import stream_outbox_events
from apps.chatlab.events import build_chatlab_transport_envelope


async def _collect_first_sse_event(*, simulation_id: int, envelope_builder) -> dict:
    response = await sync_to_async(stream_outbox_events, thread_sensitive=False)(
        simulation_id=simulation_id,
        heartbeat_interval_seconds=10.0,
        poll_interval_seconds=0.01,
        envelope_builder=envelope_builder,
    )

    async for chunk in response.streaming_content:
        decoded = chunk.decode() if isinstance(chunk, bytes) else chunk
        if decoded.startswith("data: "):
            return json.loads(decoded[6:])

    raise AssertionError("SSE stream did not yield an event payload")


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Events Test Role")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="events-user@example.com",
        role=user_role,
    )


@pytest.fixture
def auth_client(test_user):
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="Events Patient",
    )


@pytest.fixture
def conversation(simulation):
    from apps.simcore.models import Conversation, ConversationType

    patient_type = ConversationType.objects.get(slug="simulated_patient")
    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=patient_type,
        display_name="Events Patient",
        display_initials="EP",
    )


@pytest.mark.django_db
def test_events_catchup_enriches_chat_media_payload(
    auth_client, simulation, conversation, test_user
):
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.models import OutboxEvent
    from apps.simcore.models import SimulationImage

    message = Message.objects.create(
        simulation=simulation,
        conversation=conversation,
        sender=test_user,
        content="Image payload event",
        role=RoleChoices.ASSISTANT,
        message_type=Message.MessageType.IMAGE,
        is_from_ai=True,
        display_name="Patient",
    )

    buf = BytesIO()
    Image.new("RGB", (24, 24), color=(200, 120, 20)).save(buf, format="PNG")
    media = SimulationImage(
        simulation=simulation,
        description="event image",
        mime_type="image/png",
    )
    media.original.save("event.png", ContentFile(buf.getvalue()), save=False)
    media.save()
    message.media.add(media)

    OutboxEvent.objects.create(
        event_type="chat.message_created",
        simulation_id=simulation.id,
        payload={
            "message_id": message.id,
            "content": message.content,
        },
        idempotency_key=f"chat.message_created:{message.id}:test",
    )

    response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]

    event = payload["items"][0]
    assert event["event_type"] == "chat.message_created"
    assert "media_list" in event["payload"]
    assert "mediaList" in event["payload"]
    assert len(event["payload"]["media_list"]) == 1
    assert event["payload"]["media_list"][0]["original_url"].startswith("http://testserver/")
    assert event["payload"]["media_list"][0]["thumbnail_url"].startswith("http://testserver/")


@pytest.mark.django_db
def test_events_catchup_preserves_metadata_results_payload(auth_client, simulation):
    from apps.common.models import OutboxEvent

    OutboxEvent.objects.create(
        event_type="simulation.metadata.results_created",
        simulation_id=simulation.id,
        payload={
            "tool": "patient_results",
            "results": [
                {
                    "id": 501,
                    "key": "lab_results_available",
                    "value": "true",
                }
            ],
        },
        idempotency_key=f"simulation.metadata.results_created:{simulation.id}:501",
        correlation_id="corr-501",
    )

    response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]

    event = payload["items"][0]
    assert event["event_type"] == "simulation.metadata.results_created"
    assert event["payload"]["tool"] == "patient_results"
    assert event["payload"]["results"][0]["key"] == "lab_results_available"


@pytest.mark.django_db
def test_chat_message_transport_parity_between_catchup_and_sse(
    auth_client, simulation, conversation, test_user
):
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.models import OutboxEvent
    from apps.simcore.models import SimulationImage

    message = Message.objects.create(
        simulation=simulation,
        conversation=conversation,
        sender=test_user,
        content="Parity image payload",
        role=RoleChoices.ASSISTANT,
        message_type=Message.MessageType.IMAGE,
        is_from_ai=True,
        display_name="Patient",
    )

    buf = BytesIO()
    Image.new("RGB", (16, 16), color=(10, 20, 30)).save(buf, format="PNG")
    media = SimulationImage(
        simulation=simulation,
        description="parity image",
        mime_type="image/png",
    )
    media.original.save("parity.png", ContentFile(buf.getvalue()), save=False)
    media.save()
    message.media.add(media)

    OutboxEvent.objects.create(
        event_type="chat.message_created",
        simulation_id=simulation.id,
        payload={"message_id": message.id, "content": message.content},
        idempotency_key=f"chat.message_created:{message.id}:parity",
    )

    catchup_response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert catchup_response.status_code == 200
    catchup_event = catchup_response.json()["items"][0]

    request = RequestFactory().get("/api/v1/simulations/events/", HTTP_HOST="testserver")
    sse_event = async_to_sync(_collect_first_sse_event)(
        simulation_id=simulation.id,
        envelope_builder=partial(build_chatlab_transport_envelope, request=request),
    )

    assert sse_event == catchup_event


@pytest.mark.django_db
def test_metadata_results_transport_parity_between_catchup_and_sse(auth_client, simulation):
    from apps.common.models import OutboxEvent

    OutboxEvent.objects.create(
        event_type="simulation.metadata.results_created",
        simulation_id=simulation.id,
        payload={
            "tool": "patient_results",
            "results": [
                {
                    "id": 501,
                    "key": "lab_results_available",
                    "value": "true",
                }
            ],
        },
        idempotency_key=f"simulation.metadata.results_created:{simulation.id}:parity",
        correlation_id="corr-501",
    )

    catchup_response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert catchup_response.status_code == 200
    catchup_event = catchup_response.json()["items"][0]

    request = RequestFactory().get("/api/v1/simulations/events/", HTTP_HOST="testserver")
    sse_event = async_to_sync(_collect_first_sse_event)(
        simulation_id=simulation.id,
        envelope_builder=partial(build_chatlab_transport_envelope, request=request),
    )

    assert sse_event == catchup_event
