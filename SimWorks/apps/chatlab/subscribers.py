"""App-owned ChatLab subscribers for generic orchestration hooks."""

from __future__ import annotations

import logging

from django.dispatch import receiver

from apps.chatlab.events import emit_chat_message_created_sync, emit_legacy_metadata_created_sync
from apps.chatlab.models import Message
from apps.chatlab.signals import _emit_message_status
from apps.chatlab.utils import broadcast_patient_results
from apps.simcore.models import SimulationMetadata
from orchestrai_django.signals import domain_object_created, service_call_succeeded

logger = logging.getLogger(__name__)


def _attempt_id_from_context(context: dict | None) -> str | None:
    context = context or {}
    return context.get("_service_call_attempt_id") or context.get("service_call_attempt_id")


def _correlation_id_from_call(call) -> str | None:
    correlation_id = getattr(call, "correlation_id", None)
    return str(correlation_id) if correlation_id else None


@receiver(service_call_succeeded)
def handle_service_call_succeeded(
    sender,
    call=None,
    context: dict | None = None,
    **kwargs,
):
    """Map generic service success to ChatLab-owned delivery state changes."""
    context = context or {}
    message_id = context.get("user_msg") or context.get("user_msg_id")
    if not message_id:
        return

    try:
        message = Message.objects.get(pk=message_id)
    except Message.DoesNotExist:
        logger.warning("Successful service references missing message %s", message_id)
        return

    if message.delivery_status == Message.DeliveryStatus.DELIVERED:
        return

    message.delivery_status = Message.DeliveryStatus.DELIVERED
    message.delivery_error_code = ""
    message.delivery_error_text = ""
    message.delivery_retryable = False
    message.save(
        update_fields=[
            "delivery_status",
            "delivery_error_code",
            "delivery_error_text",
            "delivery_retryable",
        ]
    )
    _emit_message_status(
        simulation_id=message.simulation_id,
        message_id=message.id,
        status=Message.DeliveryStatus.DELIVERED,
        retryable=message.delivery_retryable,
        error_code=message.delivery_error_code,
        error_text=message.delivery_error_text,
    )


@receiver(domain_object_created)
def handle_domain_object_created(
    sender,
    call=None,
    context: dict | None = None,
    **kwargs,
):
    """Emit ChatLab durable events after generic domain persistence succeeds."""
    attempt_id = _attempt_id_from_context(context)
    if not attempt_id:
        return

    correlation_id = _correlation_id_from_call(call)

    ai_messages = list(
        Message.objects.select_related("conversation__conversation_type")
        .prefetch_related("media")
        .filter(service_call_attempt_id=attempt_id, is_from_ai=True)
    )
    for message in ai_messages:
        emit_chat_message_created_sync(message, correlation_id=correlation_id)

    metadata_items = list(SimulationMetadata.objects.filter(service_call_attempt_id=attempt_id))
    if metadata_items:
        broadcast_patient_results(metadata_items, correlation_id=correlation_id)
        emit_legacy_metadata_created_sync(metadata_items, correlation_id=correlation_id)
