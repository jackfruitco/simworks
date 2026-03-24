"""Tests for catch-up events API."""

from io import BytesIO

from django.core.files.base import ContentFile
from django.test import Client
from PIL import Image
import pytest

from api.v1.auth import create_access_token
from apps.common.outbox.event_types import MESSAGE_CREATED, PATIENT_RESULTS_UPDATED


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
        event_type=MESSAGE_CREATED,
        simulation_id=simulation.id,
        payload={
            "message_id": message.id,
            "content": message.content,
        },
        idempotency_key=f"{MESSAGE_CREATED}:{message.id}:test",
    )

    response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]

    event = payload["items"][0]
    assert event["event_type"] == MESSAGE_CREATED
    assert "media_list" in event["payload"]
    assert "mediaList" in event["payload"]
    assert len(event["payload"]["media_list"]) == 1
    assert event["payload"]["media_list"][0]["original_url"].startswith("http://testserver/")
    assert event["payload"]["media_list"][0]["thumbnail_url"].startswith("http://testserver/")


@pytest.mark.django_db
def test_events_catchup_preserves_metadata_results_payload(auth_client, simulation):
    from apps.common.models import OutboxEvent

    OutboxEvent.objects.create(
        event_type=PATIENT_RESULTS_UPDATED,
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
        idempotency_key=f"{PATIENT_RESULTS_UPDATED}:{simulation.id}:501",
        correlation_id="corr-501",
    )

    response = auth_client.get(f"/api/v1/simulations/{simulation.id}/events/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]

    event = payload["items"][0]
    assert event["event_type"] == PATIENT_RESULTS_UPDATED
    assert event["payload"]["tool"] == "patient_results"
    assert event["payload"]["results"][0]["key"] == "lab_results_available"
