"""Outbox pattern helpers for durable event delivery.

This module provides functions to:
1. Create outbox events atomically with domain changes
2. Build WebSocket event envelopes from outbox events
3. Trigger immediate drain for low-latency delivery

Usage:
    from apps.common.outbox import enqueue_event, poke_drain

    # In a view or signal handler
    async def create_message_handler(message):
        # ... create message ...

        # Create outbox event (in same transaction ideally)
        await enqueue_event(
            event_type="message.created",
            simulation_id=message.simulation_id,
            payload={"message_id": message.pk, "content": message.content},
            idempotency_key=f"message.created:{message.pk}",
            correlation_id=request.correlation_id,
        )

        # Trigger immediate delivery
        await poke_drain()
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


async def enqueue_event(
    event_type: str,
    simulation_id: int,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
) -> "OutboxEvent | None":
    """Create an outbox event atomically.

    Args:
        event_type: Event type (e.g., 'message.created', 'simulation.ended')
        simulation_id: Simulation ID for routing to correct WebSocket group
        payload: Event payload as a dict (will be stored as JSON)
        idempotency_key: Unique key to prevent duplicate events.
                        If not provided, a UUID will be generated.
        correlation_id: Request correlation ID for tracing

    Returns:
        The created OutboxEvent, or None if a duplicate was detected

    Example:
        event = await enqueue_event(
            event_type="message.created",
            simulation_id=123,
            payload={"message_id": 456, "content": "Hello"},
            idempotency_key="message.created:456",
        )
    """
    from apps.common.models import OutboxEvent

    if idempotency_key is None:
        idempotency_key = f"{event_type}:{uuid.uuid4()}"

    @sync_to_async
    def _create():
        try:
            with transaction.atomic():
                return OutboxEvent.objects.create(
                    event_type=event_type,
                    simulation_id=simulation_id,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                )
        except IntegrityError:
            # Duplicate idempotency_key - event already exists
            logger.debug(
                "Duplicate outbox event skipped: %s",
                idempotency_key,
            )
            return None

    event = await _create()

    if event:
        logger.debug(
            "Outbox event created: %s (%s) for simulation %d",
            event.id,
            event_type,
            simulation_id,
        )

    return event


def enqueue_event_sync(
    event_type: str,
    simulation_id: int,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
) -> "OutboxEvent | None":
    """Synchronous version of enqueue_event.

    Use this when calling from synchronous code (e.g., Django signals).
    """
    from apps.common.models import OutboxEvent

    if idempotency_key is None:
        idempotency_key = f"{event_type}:{uuid.uuid4()}"

    try:
        with transaction.atomic():
            event = OutboxEvent.objects.create(
                event_type=event_type,
                simulation_id=simulation_id,
                payload=payload,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
            logger.debug(
                "Outbox event created: %s (%s) for simulation %d",
                event.id,
                event_type,
                simulation_id,
            )
            return event
    except IntegrityError:
        logger.debug(
            "Duplicate outbox event skipped: %s",
            idempotency_key,
        )
        return None


def build_ws_envelope(event: "OutboxEvent") -> dict[str, Any]:
    """Build a WebSocket event envelope from an OutboxEvent.

    The envelope format follows the standardized structure defined in CLAUDE.md:

    {
        "event_id": "<uuid>",
        "event_type": "message.created",
        "created_at": "2024-01-01T12:00:00Z",
        "correlation_id": "<uuid>|null",
        "payload": { ... }
    }

    Args:
        event: The OutboxEvent to convert

    Returns:
        A dict suitable for sending via WebSocket
    """
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "created_at": event.created_at.isoformat() if event.created_at else datetime.now(timezone.utc).isoformat(),
        "correlation_id": event.correlation_id,
        "payload": event.payload,
    }


async def poke_drain() -> None:
    """Trigger immediate drain for low-latency delivery.

    This function schedules the drain task to run immediately,
    providing low-latency delivery while the periodic scheduler
    ensures reliability.

    In hybrid mode, events are delivered via:
    1. Immediate poke after creation (low latency)
    2. Periodic scheduler every 15 seconds (reliability)
    """
    # Import here to avoid circular imports
    try:
        from apps.common.tasks import drain_outbox

        # Schedule task to run immediately
        # Using delay() for async execution
        drain_outbox.delay()
        logger.debug("Drain task poked for immediate delivery")
    except Exception as e:
        # Don't fail if Celery isn't available
        logger.warning("Failed to poke drain task: %s", e)


def poke_drain_sync() -> None:
    """Synchronous version of poke_drain."""
    try:
        from apps.common.tasks import drain_outbox

        drain_outbox.delay()
        logger.debug("Drain task poked for immediate delivery")
    except Exception as e:
        logger.warning("Failed to poke drain task: %s", e)


async def get_events_for_simulation(
    simulation_id: int,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list["OutboxEvent"], str | None, bool]:
    """Get events for a simulation (catch-up endpoint).

    This allows clients to fetch missed events after reconnection.

    Args:
        simulation_id: Simulation to get events for
        cursor: Event ID to start after (exclusive)
        limit: Maximum number of events to return

    Returns:
        Tuple of (events, next_cursor, has_more)
    """
    from apps.common.models import OutboxEvent

    @sync_to_async
    def _query():
        queryset = OutboxEvent.objects.filter(
            simulation_id=simulation_id,
        ).order_by("created_at")

        if cursor:
            try:
                cursor_uuid = uuid.UUID(cursor)
                # Get the created_at of the cursor event
                try:
                    cursor_event = OutboxEvent.objects.get(id=cursor_uuid)
                    queryset = queryset.filter(created_at__gt=cursor_event.created_at)
                except OutboxEvent.DoesNotExist:
                    pass  # Invalid cursor, return from beginning
            except ValueError:
                pass  # Invalid UUID, return from beginning

        events = list(queryset[: limit + 1])
        has_more = len(events) > limit
        if has_more:
            events = events[:limit]

        next_cursor = str(events[-1].id) if has_more and events else None

        return events, next_cursor, has_more

    return await _query()
