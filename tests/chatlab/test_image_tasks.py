"""Tests for ChatLab clinical image generation tasks."""

from io import BytesIO
from unittest.mock import patch

from PIL import Image
import pytest

from apps.chatlab.models import Message, MessageMediaLink, RoleChoices
from apps.chatlab.tasks import run_generate_patient_image


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (24, 24), color=(220, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Image Task Test")


@pytest.fixture
def user(db, user_role):
    from apps.accounts.models import User

    return User.objects.create_user(
        email="img-task@example.com",
        password="testpass123",
        role=user_role,
    )


@pytest.fixture
def simulation(db, user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=user,
        chief_complaint="Wrist pain and swelling",
        sim_patient_full_name="Image Patient",
    )


@pytest.fixture
def patient_conversation(db, simulation):
    from apps.simcore.models import Conversation, ConversationType

    conv_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient",
        defaults={
            "display_name": "Simulated Patient",
            "ai_persona": "patient",
            "locks_with_simulation": True,
            "available_in": ["chatlab"],
            "sort_order": 0,
        },
    )
    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=conv_type,
        display_name=simulation.sim_patient_display_name or "Patient",
        display_initials=simulation.sim_patient_initials or "Pt",
    )


@pytest.fixture
def source_message(db, simulation, patient_conversation):
    from apps.common.utils.accounts import get_system_user

    return Message.objects.create(
        simulation=simulation,
        conversation=patient_conversation,
        sender=get_system_user(),
        content="I can send you a photo of the swelling.",
        role=RoleChoices.ASSISTANT,
        message_type=Message.MessageType.TEXT,
        is_from_ai=True,
        display_name=simulation.sim_patient_display_name or "Patient",
    )


@pytest.mark.django_db
def test_generate_patient_image_task_success(source_message):
    from apps.chatlab.image_generation import GeneratedImage
    from apps.common.models import OutboxEvent

    with patch(
        "apps.chatlab.tasks.generate_patient_image",
        return_value=GeneratedImage(
            image_bytes=_png_bytes(),
            mime_type="image/png",
            provider_id="img_123",
        ),
    ):
        image_message_id = run_generate_patient_image(
            simulation_id=source_message.simulation_id,
            conversation_id=source_message.conversation_id,
            source_message_id=source_message.id,
            prompt="close-up smartphone photo of swollen left wrist",
            caption="Here is my wrist now.",
            clinical_focus="left wrist swelling",
            correlation_id="corr-123",
        )

    image_message = Message.objects.get(id=image_message_id)
    assert image_message.message_type == Message.MessageType.IMAGE
    assert image_message.source_message_id == source_message.id
    assert image_message.is_from_ai is True
    assert image_message.content == "Here is my wrist now."

    link = MessageMediaLink.objects.get(message=image_message)
    assert link.media.provider_id == "img_123"
    assert link.media.mime_type == "image/png"

    event = OutboxEvent.objects.get(idempotency_key=f"chat.message_created:{image_message.id}")
    assert event.event_type == "chat.message_created"
    assert event.payload["message_id"] == image_message.id
    assert event.payload["source_message_id"] == source_message.id
    assert len(event.payload["media_list"]) == 1
    assert len(event.payload["mediaList"]) == 1


@pytest.mark.django_db
def test_generate_patient_image_task_dedupes_by_source_message(source_message):
    from apps.chatlab.image_generation import GeneratedImage

    with patch(
        "apps.chatlab.tasks.generate_patient_image",
        return_value=GeneratedImage(
            image_bytes=_png_bytes(),
            mime_type="image/png",
            provider_id="img_456",
        ),
    ) as mock_generate:
        first_id = run_generate_patient_image(
            simulation_id=source_message.simulation_id,
            conversation_id=source_message.conversation_id,
            source_message_id=source_message.id,
            prompt="left wrist photo",
        )
        second_id = run_generate_patient_image(
            simulation_id=source_message.simulation_id,
            conversation_id=source_message.conversation_id,
            source_message_id=source_message.id,
            prompt="left wrist photo",
        )

    assert first_id == second_id
    assert mock_generate.call_count == 1
    assert (
        Message.objects.filter(
            source_message_id=source_message.id,
            message_type=Message.MessageType.IMAGE,
            is_from_ai=True,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_generate_patient_image_task_failure_creates_fallback_text(source_message):
    from apps.chatlab.image_generation import ImageGenerationError

    with patch(
        "apps.chatlab.tasks.generate_patient_image",
        side_effect=ImageGenerationError("blocked by provider"),
    ):
        fallback_id = run_generate_patient_image(
            simulation_id=source_message.simulation_id,
            conversation_id=source_message.conversation_id,
            source_message_id=source_message.id,
            prompt="left wrist photo",
            clinical_focus="left wrist swelling",
        )

    fallback = Message.objects.get(id=fallback_id)
    assert fallback.message_type == Message.MessageType.TEXT
    assert fallback.source_message_id == source_message.id
    assert "could not generate" in fallback.content.lower()
    assert MessageMediaLink.objects.filter(message=fallback).count() == 0
