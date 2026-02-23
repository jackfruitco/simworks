"""Celery tasks for common functionality.

Includes the outbox drain worker for durable event delivery.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Configuration with defaults
DRAIN_BATCH_SIZE = getattr(settings, "OUTBOX_DRAIN_BATCH_SIZE", 100)
DRAIN_MAX_ATTEMPTS = getattr(settings, "OUTBOX_DRAIN_MAX_ATTEMPTS", 10)
DRAIN_LOCK_TIMEOUT = getattr(settings, "OUTBOX_DRAIN_LOCK_TIMEOUT", 30)  # seconds


@shared_task(
    bind=True,
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def drain_outbox(self):
    """Drain pending outbox events to WebSocket channel layer.

    This task runs:
    1. Periodically via Celery Beat (every 15 seconds for reliability)
    2. Immediately when poked after event creation (for low latency)

    It uses select_for_update(skip_locked=True) for safe concurrent execution.
    """
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    from apps.common.models import OutboxEvent
    from apps.common.outbox import build_ws_envelope

    channel_layer = get_channel_layer()
    if not channel_layer:
        logger.warning("No channel layer configured, skipping outbox drain")
        return

    # Find pending events, skip any already being processed
    with transaction.atomic():
        pending_events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                status=OutboxEvent.EventStatus.PENDING,
                delivery_attempts__lt=DRAIN_MAX_ATTEMPTS,
            )
            .order_by("created_at")[:DRAIN_BATCH_SIZE]
        )

        if not pending_events:
            return

        logger.info("Draining %d outbox events", len(pending_events))

        delivered_count = 0
        failed_count = 0

        for event in pending_events:
            try:
                # Build the WebSocket envelope
                envelope = build_ws_envelope(event)

                # Send to the simulation's channel group
                group_name = f"simulation_{event.simulation_id}"

                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        "type": "outbox.event",
                        "event": envelope,
                    },
                )

                # Mark as delivered
                event.mark_delivered()
                delivered_count += 1

                logger.debug(
                    "Delivered outbox event %s (%s) to group %s",
                    event.id,
                    event.event_type,
                    group_name,
                )

            except Exception as e:
                logger.warning(
                    "Failed to deliver outbox event %s: %s",
                    event.id,
                    e,
                )
                event.increment_attempts()

                # Mark as failed if max attempts reached
                if event.delivery_attempts >= DRAIN_MAX_ATTEMPTS:
                    event.mark_failed(str(e))
                    failed_count += 1

        logger.info(
            "Outbox drain complete: %d delivered, %d failed",
            delivered_count,
            failed_count,
        )


@shared_task(
    bind=True,
    ignore_result=True,
)
def cleanup_delivered_events(self, days_old: int = 7):
    """Clean up old delivered events from the outbox.

    This task should run periodically (e.g., daily) to prevent
    the outbox table from growing indefinitely.

    Args:
        days_old: Delete events delivered more than this many days ago
    """
    from datetime import timedelta
    from apps.common.models import OutboxEvent

    cutoff = timezone.now() - timedelta(days=days_old)

    deleted_count, _ = OutboxEvent.objects.filter(
        status=OutboxEvent.EventStatus.DELIVERED,
        delivered_at__lt=cutoff,
    ).delete()

    if deleted_count > 0:
        logger.info("Cleaned up %d old outbox events", deleted_count)


@shared_task(
    bind=True,
    ignore_result=True,
)
def retry_failed_events(self):
    """Retry failed events that might have been transient failures.

    This task resets failed events to pending status so they can
    be retried by the drain worker.
    """
    from datetime import timedelta

    from apps.common.models import OutboxEvent

    # Only retry events that failed less than 24 hours ago
    cutoff = timezone.now() - timedelta(hours=24)

    # Reset status to pending, keeping the delivery_attempts count
    updated = OutboxEvent.objects.filter(
        status=OutboxEvent.EventStatus.FAILED,
        created_at__gt=cutoff,
    ).update(status=OutboxEvent.EventStatus.PENDING)

    if updated > 0:
        logger.info("Reset %d failed events for retry", updated)
