"""Helper functions for broadcasting domain objects via outbox pattern.

This module provides reusable utilities for creating outbox events
from persisted AI response schemas, reducing code duplication and
ensuring consistent WebSocket broadcasting patterns.

Usage:
    from apps.common.outbox.helpers import broadcast_domain_objects
    from orchestrai_django.persistence import PersistContext

    async def post_persist(self, results, context: PersistContext):
        await broadcast_domain_objects(
            event_type="feedback.created",
            objects=results.get("metadata", []),
            context=context,
            payload_builder=lambda obj: {"id": obj.id, "key": obj.key},
        )
"""

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestrai_django.persistence import PersistContext

logger = logging.getLogger(__name__)


async def broadcast_domain_objects(
    event_type: str,
    objects: list[Any],
    context: "PersistContext",
    *,
    payload_builder: Callable[[Any], dict],
) -> None:
    """Broadcast domain objects via outbox pattern for WebSocket delivery.

    Creates outbox events for each object in the list, ensuring atomic
    persistence with the domain changes. Events are delivered asynchronously
    by the drain worker to connected WebSocket clients.

    This helper provides:
    - Automatic idempotency key generation (event_type:object_id)
    - Correlation ID propagation from persistence context
    - Immediate drain trigger for low-latency delivery
    - Consistent event structure across all AI responses

    Args:
        event_type: WebSocket event type (e.g., 'feedback.created', 'metadata.created')
        objects: List of persisted domain objects to broadcast
        context: PersistContext with simulation_id, correlation_id, etc. (from orchestrai_django.persistence)
        payload_builder: Function that takes a domain object and returns
                        the event payload dict (e.g., lambda obj: {"id": obj.id})

    Returns:
        None - events are created in the outbox for async delivery

    Example:
        >>> await broadcast_domain_objects(
        ...     event_type="feedback.created",
        ...     objects=[feedback1, feedback2],
        ...     context=persist_context,
        ...     payload_builder=lambda fb: {
        ...         "feedback_id": fb.id,
        ...         "key": fb.key,
        ...         "value": fb.value,
        ...     },
        ... )

    Note:
        - Objects must have an 'id' attribute for idempotency key generation
        - Empty object lists are no-ops (no events created, no drain triggered)
        - Failures to create outbox events are logged but don't raise exceptions
          (broadcast is a non-critical side effect)
    """
    if not objects:
        logger.debug("No objects to broadcast for event_type=%s", event_type)
        return

    from .outbox import enqueue_event, poke_drain

    events_created = 0

    for obj in objects:
        try:
            # Build payload using caller-provided function
            payload = payload_builder(obj)

            # Generate idempotency key from event type + object ID
            # This prevents duplicate events if post_persist runs multiple times
            idempotency_key = f"{event_type}:{obj.id}"

            # Create outbox event
            event = await enqueue_event(
                event_type=event_type,
                simulation_id=context.simulation_id,
                payload=payload,
                idempotency_key=idempotency_key,
                correlation_id=context.correlation_id,
            )

            if event:
                events_created += 1
                logger.debug(
                    "Outbox event created: %s (event_id=%s) for object %s",
                    event_type,
                    event.id,
                    obj.id,
                )
            else:
                logger.debug(
                    "Outbox event skipped (duplicate): %s for object %s",
                    event_type,
                    obj.id,
                )

        except Exception as exc:
            # Log but don't raise - broadcast is a non-critical side effect
            logger.warning(
                "Failed to create outbox event for %s (object %s): %s",
                event_type,
                getattr(obj, "id", "unknown"),
                exc,
                exc_info=True,
            )

    if events_created > 0:
        # Trigger immediate delivery for low latency
        await poke_drain()
        logger.info(
            "Broadcast complete: %d %s events enqueued",
            events_created,
            event_type,
        )
