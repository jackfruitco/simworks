# SimWorks/chatlab/signals.py
"""
ChatLab signal receivers for side effects (WebSocket broadcasting).

Domain persistence is now handled by persistence handlers in chatlab/orca/persist/.
These signals only handle non-critical side effects like WebSocket notifications.

Messages are now broadcast via the outbox pattern for:
1. Durability - events are persisted before broadcast
2. Deduplication - envelope format with event_id enables client-side dedup
3. Consistency - atomic with domain changes
"""

import logging
from asgiref.sync import async_to_sync
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Message
from .utils import broadcast_patient_results
from apps.simcore.models import Simulation, SimulationMetadata
from orchestrai_django.signals import ai_response_failed

logger = logging.getLogger(__name__)
USER_RETRY_LIMIT = 2


def _emit_message_status(
    *,
    simulation_id: int,
    message_id: int,
    status: str,
    retryable: bool | None = None,
    error_code: str | None = None,
    error_text: str | None = None,
) -> None:
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    payload = {
        "id": message_id,
        "status": status,
        "retryable": retryable,
        "error_code": error_code,
        "error_text": error_text,
    }
    event = enqueue_event_sync(
        event_type="message_status_update",
        simulation_id=simulation_id,
        payload=payload,
        idempotency_key=f"message_status_update:{message_id}:{status}:{retryable}:{error_code or 'none'}",
    )
    if event:
        poke_drain_sync()


def _emit_feedback_failure(simulation_id: int, *, error_code: str, error_text: str, retryable: bool, retry_count: int) -> None:
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    event = enqueue_event_sync(
        event_type="feedback.failed",
        simulation_id=simulation_id,
        payload={
            "simulation_id": simulation_id,
            "error_code": error_code,
            "error_text": error_text,
            "retryable": retryable,
            "retry_count": retry_count,
        },
    )
    if event:
        poke_drain_sync()


@receiver(post_save, sender=Message)
def broadcast_new_message(sender, instance, created, **kwargs):
    """
    Broadcast newly created messages via WebSocket using the outbox pattern.

    **Hybrid Approach**: This signal handler now only broadcasts messages that
    are NOT created via AI schemas (e.g., admin edits, bulk imports, manual creates).

    AI-generated messages are broadcast via schema post_persist() hooks for:
    - Better cohesion (broadcast logic lives with persistence logic)
    - Context awareness (correlation_id, audit_id available)
    - Testability (test persistence + broadcast together)

    Uses the outbox pattern for:
    1. Durability - event is persisted before broadcast
    2. Deduplication - event_id in envelope enables client-side dedup
    3. Exactly-once delivery - idempotency_key prevents duplicates

    Note: This handler serves as a safety net for non-AI message creates.
    AI responses are handled in chatlab/orca/schemas/patient.py post_persist().
    """
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    # Skip AI messages - they're broadcast via schema post_persist() hooks
    # This signal only handles non-AI messages (admin edits, manual creates, etc.)
    if created and instance.is_from_ai:
        logger.debug(
            "Skipping signal broadcast for AI message %d (handled by schema post_persist)",
            instance.id,
        )
        return

    if created and not instance.is_from_ai:
        try:
            # Resolve conversation type slug (avoid N+1 via cached FK)
            conversation_type = None
            if instance.conversation_id:
                try:
                    conversation_type = instance.conversation.conversation_type.slug
                except Exception:
                    pass  # FK not prefetched; leave as None

            # Build payload matching the existing broadcast_message format
            payload = {
                "id": instance.id,
                "message_id": instance.id,  # Explicit message_id for deduplication
                "role": instance.role,
                "content": instance.content or "",
                "timestamp": instance.timestamp.isoformat() if instance.timestamp else None,
                "status": instance.delivery_status,
                "delivery_status": instance.delivery_status,
                "delivery_retryable": instance.delivery_retryable,
                "delivery_error_code": instance.delivery_error_code or "",
                "delivery_error_text": instance.delivery_error_text or "",
                "messageType": instance.message_type,
                "isFromAi": instance.is_from_ai,
                "isFromAI": instance.is_from_ai,  # Alias for compatibility
                "displayName": instance.display_name or "",
                "senderId": instance.sender_id,
                "sender_id": instance.sender_id,  # Snake_case alias
                "conversation_id": instance.conversation_id,
                "conversation_type": conversation_type,
            }

            # Create outbox event with idempotency key based on message ID
            event = enqueue_event_sync(
                event_type="chat.message_created",
                simulation_id=instance.simulation_id,
                payload=payload,
                idempotency_key=f"chat.message_created:{instance.id}",
            )

            if event:
                # Trigger immediate delivery
                poke_drain_sync()
                logger.debug(
                    "Non-AI message %d enqueued to outbox (event %s)",
                    instance.id,
                    event.id,
                )
            else:
                logger.debug(
                    "Message %d already in outbox (duplicate)",
                    instance.id,
                )

        except Exception as exc:
            logger.warning(
                "Outbox enqueue failed for Message %d: %s",
                instance.id,
                exc,
            )
            # Don't raise - this is a non-critical side effect


@receiver(ai_response_failed)
def handle_ai_response_failed(
    sender,
    call_id=None,
    error: str = "",
    context: dict | None = None,
    reason_code: str | None = None,
    user_retryable: bool | None = None,
    **kwargs,
):
    """Map terminal service failures to user-visible chat/simulation state."""
    from orchestrai_django.models import ServiceCall, CallStatus

    context = context or {}
    service_identity = ""
    call_context = {}
    if call_id:
        try:
            call = ServiceCall.objects.only("service_identity", "status", "context").get(pk=call_id)
            service_identity = call.service_identity or ""
            call_context = call.context or {}
            if call.status != CallStatus.FAILED:
                logger.info(
                    "Ignoring non-terminal ai_response_failed signal",
                    extra={"call_id": call_id, "status": call.status},
                )
                return
        except Exception:
            logger.warning("Unable to resolve service call %s for failure routing", call_id)

    message_id = (
        call_context.get("user_msg")
        or call_context.get("user_msg_id")
        or context.get("user_msg")
        or context.get("user_msg_id")
    )
    simulation_id = call_context.get("simulation_id") or context.get("simulation_id")

    if not call_id and (message_id or simulation_id):
        logger.info(
            "Ignoring ai_response_failed without call_id to avoid non-terminal transitions",
            extra={
                "message_id": message_id,
                "simulation_id": simulation_id,
                "reason_code": reason_code,
            },
        )
        return

    # Message-level failure: failed outgoing message should remain with retry affordance.
    if message_id:
        try:
            message = Message.objects.get(pk=message_id)
        except Message.DoesNotExist:
            logger.warning("Failed service references missing message %s", message_id)
            return

        retryable = (
            bool(user_retryable) if user_retryable is not None else True
        ) and message.delivery_retry_count < USER_RETRY_LIMIT
        logger.info(
            "Marking outgoing message as failed after terminal service failure",
            extra={
                "call_id": call_id,
                "message_id": message.id,
                "simulation_id": message.simulation_id,
                "reason_code": reason_code,
                "retryable": retryable,
            },
        )
        message.delivery_status = Message.DeliveryStatus.FAILED
        message.delivery_error_code = reason_code or "ai_processing_failed"
        message.delivery_error_text = (
            "Message failed to deliver to the AI service. Try again."
        )
        message.delivery_retryable = retryable
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
            status=Message.DeliveryStatus.FAILED,
            retryable=retryable,
            error_code=message.delivery_error_code,
            error_text=message.delivery_error_text,
        )
        return

    # Initial generation failure: mark simulation failed and expose retry CTA.
    if simulation_id and "GenerateInitialResponse" in service_identity:
        try:
            simulation = Simulation.objects.get(pk=simulation_id)
        except Simulation.DoesNotExist:
            return
        normalized_reason = reason_code or "failed"
        if not normalized_reason.startswith("initial_generation_"):
            normalized_reason = f"initial_generation_{normalized_reason}"
        retryable = simulation.initial_retry_count < USER_RETRY_LIMIT
        simulation.mark_failed(
            reason_code=normalized_reason,
            reason_text="Initial patient generation failed. Please try again or go back home.",
            retryable=retryable,
        )
        return

    # Feedback generation failure: keep simulation state, emit feedback-specific failure.
    if simulation_id and "GenerateInitialFeedback" in service_identity:
        try:
            simulation = Simulation.objects.get(pk=simulation_id)
        except Simulation.DoesNotExist:
            return
        feedback_reason = reason_code or "generation_failed"
        if not feedback_reason.startswith("feedback_"):
            feedback_reason = f"feedback_{feedback_reason}"
        retryable = simulation.feedback_retry_count < USER_RETRY_LIMIT
        _emit_feedback_failure(
            simulation_id=simulation.id,
            error_code=feedback_reason,
            error_text="Feedback generation failed. Please try again.",
            retryable=retryable,
            retry_count=simulation.feedback_retry_count,
        )


@receiver(post_save, sender=SimulationMetadata)
def broadcast_metadata_update(sender, instance, created, **kwargs):
    """
    Broadcast newly created SimulationMetadata via WebSocket.

    This notifies connected clients when patient results (labs, rads, metadata)
    are created, allowing the frontend to refresh tool panels via HTMX-get.

    This is a non-critical side effect that can fail safely.
    """
    if created:
        try:
            async_to_sync(broadcast_patient_results)(instance)
            logger.debug(
                f"Broadcasted SimulationMetadata {instance.id} to WebSocket clients"
            )
        except Exception as exc:
            logger.warning(
                f"WebSocket broadcast failed for SimulationMetadata {instance.id}: {exc}"
            )
            # Don't raise - this is a non-critical side effect
