"""Background tasks for ChatLab workflows."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.tasks import task

from apps.common.outbox import enqueue_event_sync, poke_drain_sync

from .image_generation import ImageGenerationError, generate_patient_image
from .media_payloads import build_chat_message_event_payload

logger = logging.getLogger(__name__)

IMAGE_FAILURE_TEXT = (
    "I could not generate a clinical image right now, but I can still describe what you would "
    "expect to see."
)


@dataclass(slots=True)
class ImageTaskContext:
    simulation_id: int
    conversation_id: int
    source_message_id: int
    prompt: str
    caption: str | None = None
    clinical_focus: str | None = None
    correlation_id: str | None = None


def _build_final_prompt(ctx: ImageTaskContext, simulation) -> str:
    lines: list[str] = [
        "Generate a clinically realistic smartphone photo requested by the patient in a medical simulation.",
        "Do not exaggerate findings, and avoid details that would not be visible in a normal phone image.",
    ]
    if simulation.chief_complaint:
        lines.append(f"Chief complaint context: {simulation.chief_complaint}")
    if simulation.prompt_message:
        lines.append(f"Scenario context: {simulation.prompt_message}")
    if ctx.clinical_focus:
        lines.append(f"Clinical focus: {ctx.clinical_focus}")
    lines.append(f"Image request: {ctx.prompt}")
    return "\n".join(lines)


def _image_extension_for_mime(mime_type: str) -> str:
    mime_to_ext = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    return mime_to_ext.get(mime_type, "png")


def _emit_chat_message_created(message, correlation_id: str | None = None) -> None:
    event = enqueue_event_sync(
        event_type="chat.message_created",
        simulation_id=message.simulation_id,
        payload=build_chat_message_event_payload(
            message,
            fallback_conversation_type="simulated_patient",
            status="completed",
        ),
        idempotency_key=f"chat.message_created:{message.id}",
        correlation_id=correlation_id,
    )
    if event:
        poke_drain_sync()


def _create_fallback_message(
    *,
    source_message,
    correlation_id: str | None,
) -> int:
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.utils.accounts import get_system_user

    existing = Message.objects.filter(
        source_message_id=source_message.id,
        message_type=Message.MessageType.TEXT,
        is_from_ai=True,
    ).first()
    if existing:
        return existing.id

    fallback = Message.objects.create(
        simulation_id=source_message.simulation_id,
        conversation_id=source_message.conversation_id,
        sender=get_system_user(),
        content=IMAGE_FAILURE_TEXT,
        role=RoleChoices.ASSISTANT,
        message_type=Message.MessageType.TEXT,
        is_from_ai=True,
        display_name=source_message.display_name,
        service_call_attempt=source_message.service_call_attempt,
        provider_response_id=source_message.provider_response_id,
        source_message=source_message,
    )
    _emit_chat_message_created(fallback, correlation_id=correlation_id)
    return fallback.id


@task
def generate_patient_image_task(
    *,
    simulation_id: int,
    conversation_id: int,
    source_message_id: int,
    prompt: str,
    caption: str | None = None,
    clinical_focus: str | None = None,
    correlation_id: str | None = None,
) -> int | None:
    """Task wrapper for generating/persisting patient images."""
    return run_generate_patient_image(
        simulation_id=simulation_id,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        prompt=prompt,
        caption=caption,
        clinical_focus=clinical_focus,
        correlation_id=correlation_id,
    )


def enqueue_generate_patient_image_task(
    *,
    simulation_id: int,
    conversation_id: int,
    source_message_id: int,
    prompt: str,
    caption: str | None = None,
    clinical_focus: str | None = None,
    correlation_id: str | None = None,
):
    """Thin indirection to make task enqueueing patchable in tests."""
    return generate_patient_image_task.enqueue(
        simulation_id=simulation_id,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        prompt=prompt,
        caption=caption,
        clinical_focus=clinical_focus,
        correlation_id=correlation_id,
    )


def run_generate_patient_image(
    *,
    simulation_id: int,
    conversation_id: int,
    source_message_id: int,
    prompt: str,
    caption: str | None = None,
    clinical_focus: str | None = None,
    correlation_id: str | None = None,
) -> int | None:
    """Generate/persist a clinical image as a separate AI message."""
    from apps.chatlab.models import Message, MessageMediaLink, RoleChoices
    from apps.common.utils.accounts import get_system_user
    from apps.simcore.models import SimulationImage

    ctx = ImageTaskContext(
        simulation_id=simulation_id,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        prompt=prompt,
        caption=caption,
        clinical_focus=clinical_focus,
        correlation_id=correlation_id,
    )

    source_message = (
        Message.objects.select_related("simulation")
        .filter(
            id=ctx.source_message_id,
            simulation_id=ctx.simulation_id,
            conversation_id=ctx.conversation_id,
        )
        .first()
    )
    if not source_message:
        logger.warning("Image task source message not found: %s", ctx.source_message_id)
        return None

    existing = Message.objects.filter(
        source_message_id=ctx.source_message_id,
        message_type=Message.MessageType.IMAGE,
        is_from_ai=True,
    ).first()
    if existing:
        return existing.id

    final_prompt = _build_final_prompt(ctx, source_message.simulation)
    try:
        generated = generate_patient_image(prompt=final_prompt)
    except ImageGenerationError:
        logger.exception(
            "Image generation failed for source message %s", ctx.source_message_id, exc_info=True
        )
        return _create_fallback_message(
            source_message=source_message,
            correlation_id=ctx.correlation_id,
        )

    try:
        with transaction.atomic():
            locked_source = (
                Message.objects.select_for_update()
                .select_related("simulation")
                .get(id=ctx.source_message_id)
            )

            existing = Message.objects.filter(
                source_message_id=ctx.source_message_id,
                message_type=Message.MessageType.IMAGE,
                is_from_ai=True,
            ).first()
            if existing:
                return existing.id

            ext = _image_extension_for_mime(generated.mime_type)
            filename = f"chatlab-image-sim{ctx.simulation_id}-msg{ctx.source_message_id}.{ext}"
            sim_image = SimulationImage(
                simulation_id=ctx.simulation_id,
                provider_id=generated.provider_id,
                mime_type=generated.mime_type,
                description=(ctx.clinical_focus or "clinical image")[:100],
            )
            sim_image.original.save(
                filename,
                ContentFile(generated.image_bytes),
                save=False,
            )
            sim_image.save()

            image_message = Message.objects.create(
                simulation_id=ctx.simulation_id,
                conversation_id=ctx.conversation_id,
                sender=get_system_user(),
                content=(ctx.caption or ""),
                role=RoleChoices.ASSISTANT,
                message_type=Message.MessageType.IMAGE,
                is_from_ai=True,
                display_name=locked_source.display_name,
                service_call_attempt=locked_source.service_call_attempt,
                provider_response_id=locked_source.provider_response_id,
                source_message=locked_source,
            )
            MessageMediaLink.objects.get_or_create(
                message=image_message,
                media=sim_image,
            )

        _emit_chat_message_created(image_message, correlation_id=ctx.correlation_id)
        return image_message.id
    except Exception:
        logger.exception(
            "Failed persisting generated image for source message %s", source_message_id
        )
        return _create_fallback_message(
            source_message=source_message,
            correlation_id=ctx.correlation_id,
        )
