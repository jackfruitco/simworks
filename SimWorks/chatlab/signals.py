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
from core.outbox import enqueue_event_sync, poke_drain_sync
from simulation.models import SimulationMetadata

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def broadcast_new_message(sender, instance, created, **kwargs):
    """
    Broadcast newly created messages via WebSocket using the outbox pattern.

    Uses the outbox pattern for:
    1. Durability - event is persisted before broadcast
    2. Deduplication - event_id in envelope enables client-side dedup
    3. Exactly-once delivery - idempotency_key prevents duplicates

    Note: This replaces the old ai_response_ready signal handler.
    Domain persistence now happens in chatlab/orca/persist/patient.py.
    """
    if created and instance.is_from_ai:
        try:
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
                    "Message %d enqueued to outbox (event %s)",
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
