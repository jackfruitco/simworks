"""Outbox pattern for durable event delivery.

This module provides the outbox pattern implementation for SimWorks,
ensuring reliable WebSocket event delivery with at-least-once guarantees.

Public API:
    enqueue_event()        - Create outbox event (async)
    enqueue_event_sync()   - Create outbox event (sync, for Django signals)
    poke_drain()           - Trigger immediate delivery (async)
    poke_drain_sync()      - Trigger immediate delivery (sync)
    build_ws_envelope()    - Build WebSocket envelope from outbox event
    get_events_for_simulation() - Fetch events for catch-up API
    broadcast_domain_objects()  - DRY helper for schema post_persist hooks

Usage:
    # In schema post_persist hook
    from core.outbox import broadcast_domain_objects

    async def post_persist(self, results, context):
        await broadcast_domain_objects(
            event_type="feedback.created",
            objects=results.get("metadata", []),
            context=context,
            payload_builder=lambda obj: {"id": obj.id},
        )

    # In Django signal handlers
    from core.outbox import enqueue_event_sync, poke_drain_sync

    @receiver(post_save, sender=Message)
    def broadcast_message(sender, instance, created, **kwargs):
        if created:
            enqueue_event_sync(
                event_type="message.created",
                simulation_id=instance.simulation_id,
                payload={"message_id": instance.id},
            )
            poke_drain_sync()
"""

from .outbox import (
    enqueue_event,
    enqueue_event_sync,
    poke_drain,
    poke_drain_sync,
    build_ws_envelope,
    get_events_for_simulation,
)
from .helpers import broadcast_domain_objects

__all__ = [
    # Core outbox functions
    "enqueue_event",
    "enqueue_event_sync",
    "poke_drain",
    "poke_drain_sync",
    "build_ws_envelope",
    "get_events_for_simulation",
    # DRY helpers
    "broadcast_domain_objects",
]
