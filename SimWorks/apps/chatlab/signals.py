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
from apps.simcore.models import SimulationMetadata

logger = logging.getLogger(__name__)


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
                "status": "completed",
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
