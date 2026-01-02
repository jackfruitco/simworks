# SimWorks/chatlab/signals.py
"""
ChatLab signal receivers for side effects (WebSocket broadcasting).

Domain persistence is now handled by persistence handlers in chatlab/orca/persist/.
These signals only handle non-critical side effects like WebSocket notifications.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync

from .models import Message
from .utils import broadcast_message

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def broadcast_new_message(sender, instance, created, **kwargs):
    """
    Broadcast newly created messages via WebSocket.

    This is a side effect that can fail safely without affecting domain
    persistence (which happens in persistence handlers).

    Note: This replaces the old ai_response_ready signal handler.
    Domain persistence now happens in chatlab/orca/persist/patient.py.
    """
    if created and instance.is_from_ai:
        try:
            async_to_sync(broadcast_message)(instance, status="completed")
            logger.debug(f"Broadcasted Message {instance.id} to WebSocket clients")
        except Exception as exc:
            logger.warning(
                f"WebSocket broadcast failed for Message {instance.id}: {exc}"
            )
            # Don't raise - this is a non-critical side effect
