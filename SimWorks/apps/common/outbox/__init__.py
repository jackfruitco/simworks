"""Outbox pattern for durable event delivery.

This module provides the outbox pattern implementation for SimWorks,
ensuring reliable event delivery with at-least-once guarantees across
all transports (REST catch-up, SSE streaming, WebSocket).

Public API:
    enqueue_event()            - Create outbox event (async)
    enqueue_event_sync()       - Create outbox event (sync, for Django signals)
    poke_drain()               - Trigger immediate delivery (async)
    poke_drain_sync()          - Trigger immediate delivery (sync)
    build_canonical_envelope() - Build transport envelope from outbox event
    build_ws_envelope()        - Alias for build_canonical_envelope (compat)
    get_latest_cursor_sync()   - Latest raw outbox cursor for a simulation (sync)
    get_latest_cursor()        - Latest raw outbox cursor for a simulation (async)
    get_latest_event_id_sync() - Latest replayable ChatLab durable event ID (sync)
    get_latest_event_id()      - Latest replayable ChatLab durable event ID (async)
    get_events_for_simulation() - Fetch events for catch-up API

Usage:
    # In Django signal handlers
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    @receiver(post_save, sender=Message)
    def broadcast_message(sender, instance, created, **kwargs):
        if created:
            enqueue_event_sync(
                event_type="message.item.created",
                simulation_id=instance.simulation_id,
                payload={"message_id": instance.id},
            )
            poke_drain_sync()

    # In schema post_persist hooks
    from apps.common.outbox.helpers import broadcast_domain_objects

    async def post_persist(self, results, context):
        await broadcast_domain_objects(
            event_type="assessment.item.created",
            objects=results.get("metadata", []),
            context=context,
            payload_builder=lambda obj: {"id": str(obj.id)},
        )
"""

from . import event_types
from .outbox import (
    apply_outbox_cursor,
    build_canonical_envelope,
    build_ws_envelope,
    enqueue_event,
    enqueue_event_sync,
    get_events_after_event,
    get_events_after_event_sync,
    get_events_for_simulation,
    get_latest_cursor,
    get_latest_cursor_sync,
    get_latest_event_id,
    get_latest_event_id_sync,
    get_outbox_event,
    get_outbox_event_sync,
    order_outbox_queryset,
    poke_drain,
    poke_drain_sync,
)

# Note: broadcast_domain_objects is NOT exported here to avoid import issues
# during Django startup. It requires orchestrai_django.persistence.PersistContext
# which may not be ready when signals are registered.
# Import directly from apps.common.outbox.helpers where needed (in schema post_persist hooks).

__all__ = [
    "apply_outbox_cursor",
    "build_canonical_envelope",
    "build_ws_envelope",
    # common outbox functions
    "enqueue_event",
    "enqueue_event_sync",
    "event_types",
    "get_events_after_event",
    "get_events_after_event_sync",
    "get_events_for_simulation",
    "get_latest_cursor",
    "get_latest_cursor_sync",
    "get_latest_event_id",
    "get_latest_event_id_sync",
    "get_outbox_event",
    "get_outbox_event_sync",
    "order_outbox_queryset",
    "poke_drain",
    "poke_drain_sync",
]
