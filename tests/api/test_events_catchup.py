"""Tests for the ChatLab durable replay API."""

from __future__ import annotations

import uuid

from django.test import Client
from django.utils import timezone
import pytest

from api.v1.auth import create_access_token
from apps.common.outbox.event_types import MESSAGE_CREATED, SIMULATION_STATUS_UPDATED


def _attach_chatlab_session(simulation):
    from apps.chatlab.models import ChatSession

    ChatSession.objects.get_or_create(simulation=simulation)
    return simulation


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Chat Events API Test")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="eventuser@example.com",
        role=user_role,
    )


@pytest.fixture(autouse=True)
def chatlab_access(test_user):
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
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    simulation = Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="John Doe",
    )
    return _attach_chatlab_session(simulation)


@pytest.fixture
def outbox_events(simulation):
    from apps.common.models import OutboxEvent

    events = []
    for index in range(5):
        events.append(
            OutboxEvent.objects.create(
                event_type=SIMULATION_STATUS_UPDATED,
                simulation_id=simulation.pk,
                payload={"index": index, "content": f"Test content {index}"},
                idempotency_key=f"test.event:{simulation.pk}:{uuid.uuid4()}",
                correlation_id=f"corr-{index}",
            )
        )
    return events


@pytest.mark.django_db
def test_list_events_returns_durable_replay_response(auth_client, simulation, outbox_events):
    response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "has_more" in data
    assert "next_event_id" in data
    assert len(data["items"]) == 5
    first_event = data["items"][0]
    assert set(first_event.keys()) == {
        "event_id",
        "event_type",
        "created_at",
        "correlation_id",
        "payload",
    }


@pytest.mark.django_db
def test_last_event_id_pagination_is_exclusive(auth_client, simulation, outbox_events):
    first_page = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/?limit=2")
    assert first_page.status_code == 200
    first_data = first_page.json()
    assert len(first_data["items"]) == 2
    first_page_ids = [item["event_id"] for item in first_data["items"]]

    second_page = auth_client.get(
        f"/api/v1/simulations/{simulation.pk}/events/"
        f"?last_event_id={first_data['next_event_id']}&limit=2"
    )
    assert second_page.status_code == 200
    second_data = second_page.json()
    second_page_ids = [item["event_id"] for item in second_data["items"]]

    assert not (set(first_page_ids) & set(second_page_ids))
    assert second_page_ids[0] == str(outbox_events[2].id)


@pytest.mark.django_db
def test_last_event_id_handles_same_created_at_without_duplicates(auth_client, simulation):
    from apps.common.models import OutboxEvent

    events = [
        OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.pk,
            payload={"index": index},
            idempotency_key=f"same-ts:{simulation.pk}:{uuid.uuid4()}",
        )
        for index in range(3)
    ]
    shared_timestamp = timezone.now()
    OutboxEvent.objects.filter(id__in=[event.id for event in events]).update(
        created_at=shared_timestamp
    )

    first_page = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/?limit=2")
    first_data = first_page.json()
    second_page = auth_client.get(
        f"/api/v1/simulations/{simulation.pk}/events/"
        f"?last_event_id={first_data['next_event_id']}&limit=2"
    )
    second_data = second_page.json()

    first_ids = {item["event_id"] for item in first_data["items"]}
    second_ids = {item["event_id"] for item in second_data["items"]}
    assert not (first_ids & second_ids)


@pytest.mark.django_db
def test_pagination_counts_only_replayable_events(auth_client, simulation):
    from apps.common.models import OutboxEvent

    durable_events = []
    durable_events.append(
        OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.pk,
            payload={"index": 0},
            idempotency_key=f"replayable-page:{simulation.pk}:{uuid.uuid4()}",
        )
    )
    OutboxEvent.objects.create(
        event_type="typing.started",
        simulation_id=simulation.pk,
        payload={"index": 0},
        idempotency_key=f"non-replayable-page:{simulation.pk}:{uuid.uuid4()}",
    )
    durable_events.append(
        OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.pk,
            payload={"index": 1},
            idempotency_key=f"replayable-page:{simulation.pk}:{uuid.uuid4()}",
        )
    )
    OutboxEvent.objects.create(
        event_type="typing.started",
        simulation_id=simulation.pk,
        payload={"index": 1},
        idempotency_key=f"non-replayable-page:{simulation.pk}:{uuid.uuid4()}",
    )
    durable_events.append(
        OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation.pk,
            payload={"index": 2},
            idempotency_key=f"replayable-page:{simulation.pk}:{uuid.uuid4()}",
        )
    )

    first_page = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/?limit=2")
    assert first_page.status_code == 200
    first_data = first_page.json()
    assert [item["event_id"] for item in first_data["items"]] == [
        str(durable_events[0].id),
        str(durable_events[1].id),
    ]
    assert first_data["has_more"] is True
    assert first_data["next_event_id"] == str(durable_events[1].id)

    second_page = auth_client.get(
        f"/api/v1/simulations/{simulation.pk}/events/"
        f"?last_event_id={first_data['next_event_id']}&limit=2"
    )
    assert second_page.status_code == 200
    second_data = second_page.json()
    assert [item["event_id"] for item in second_data["items"]] == [str(durable_events[2].id)]
    assert second_data["has_more"] is False
    assert second_data["next_event_id"] is None


@pytest.mark.django_db
def test_invalid_last_event_id_returns_400(auth_client, simulation):
    response = auth_client.get(
        f"/api/v1/simulations/{simulation.pk}/events/?last_event_id=not-a-uuid"
    )
    assert response.status_code == 400
    assert "last_event_id" in response.json()["detail"]


@pytest.mark.django_db
def test_unknown_last_event_id_returns_400(auth_client, simulation):
    response = auth_client.get(
        f"/api/v1/simulations/{simulation.pk}/events/?last_event_id={uuid.uuid4()}"
    )
    assert response.status_code == 400
    assert "last_event_id" in response.json()["detail"]


@pytest.mark.django_db
def test_non_replayable_last_event_id_returns_400(auth_client, simulation):
    from apps.common.models import OutboxEvent

    non_replayable = OutboxEvent.objects.create(
        event_type="typing.started",
        simulation_id=simulation.pk,
        payload={"conversation_id": 123},
        idempotency_key=f"non-replayable-anchor:{simulation.pk}:{uuid.uuid4()}",
    )

    response = auth_client.get(
        f"/api/v1/simulations/{simulation.pk}/events/?last_event_id={non_replayable.id}"
    )
    assert response.status_code == 400
    assert "last_event_id" in response.json()["detail"]


@pytest.mark.django_db
def test_message_created_replay_enriches_media_payload(auth_client, simulation):
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image

    from apps.chatlab.models import Message, RoleChoices
    from apps.simcore.models import Conversation, ConversationType, SimulationImage

    patient_type = ConversationType.objects.create(
        slug=f"patient-{uuid.uuid4().hex[:8]}",
        display_name="Patient",
        ai_persona="patient",
        locks_with_simulation=True,
    )
    conversation = Conversation.objects.create(
        simulation=simulation,
        conversation_type=patient_type,
        display_name="Patient",
        display_initials="PT",
    )
    message = Message.objects.create(
        simulation=simulation,
        conversation=conversation,
        sender=simulation.user,
        content="Image payload event",
        role=RoleChoices.ASSISTANT,
        message_type=Message.MessageType.IMAGE,
        is_from_ai=True,
        display_name="Patient",
    )

    buffer = BytesIO()
    Image.new("RGB", (24, 24), color=(200, 120, 20)).save(buffer, format="PNG")
    media = SimulationImage(
        simulation=simulation,
        description="event image",
        mime_type="image/png",
    )
    media.original.save("event.png", ContentFile(buffer.getvalue()), save=False)
    media.save()
    message.media.add(media)

    from apps.common.models import OutboxEvent

    OutboxEvent.objects.create(
        event_type=MESSAGE_CREATED,
        simulation_id=simulation.id,
        payload={"message_id": message.id, "content": message.content},
        idempotency_key=f"{MESSAGE_CREATED}:{message.id}:test",
    )

    response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert response.status_code == 200
    event = response.json()["items"][0]
    assert event["event_type"] == MESSAGE_CREATED
    assert "media_list" in event["payload"]
    assert len(event["payload"]["media_list"]) == 1


@pytest.mark.django_db
def test_removed_chatlab_sse_endpoint_returns_404(auth_client, simulation):
    response = auth_client.get(f"/api/v1/simulations/{simulation.pk}/events/stream/")
    assert response.status_code == 404
