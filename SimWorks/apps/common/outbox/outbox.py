"""Outbox pattern helpers for durable event delivery.

This module provides functions to:
1. Create outbox events atomically with domain changes
2. Build canonical event envelopes for all transports (REST, SSE, WebSocket)
3. Trigger immediate drain for low-latency delivery
4. Query durable event anchors for replay/resume flows

Usage:
    from apps.common.outbox import enqueue_event, poke_drain

    # In a view or signal handler
    async def create_message_handler(message):
        # ... create message ...

        # Create outbox event (in same transaction ideally)
        await enqueue_event(
            event_type="message.item.created",
            simulation_id=message.simulation_id,
            payload={"message_id": message.pk, "content": message.content},
            idempotency_key=f"message.item.created:{message.pk}",
            correlation_id=request.correlation_id,
        )

        # Trigger immediate delivery
        await poke_drain()
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from typing import TYPE_CHECKING, Any
import uuid

from asgiref.sync import sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Q

from . import event_types

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.common.models import OutboxEvent


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert payload values to JSON-serializable primitives.

    This ensures Django JSONField inserts don't fail on values like UUID,
    datetime, or Decimal that may appear in nested payload structures.
    """
    normalized = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
    if not isinstance(normalized, dict):
        msg = "Outbox payload must serialize to a JSON object"
        raise TypeError(msg)
    return normalized


async def enqueue_event(
    event_type: str,
    simulation_id: int,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
) -> OutboxEvent | None:
    """Create an outbox event atomically.

    Args:
        event_type: Event type (e.g., 'message.item.created', 'simulation.status.updated')
        simulation_id: Simulation ID for routing to correct WebSocket group
        payload: Event payload as a dict (will be stored as JSON)
        idempotency_key: Unique key to prevent duplicate events.
                        If not provided, a UUID will be generated.
        correlation_id: Request correlation ID for tracing

    Returns:
        The created OutboxEvent, or None if a duplicate was detected

    Example:
        event = await enqueue_event(
            event_type="message.item.created",
            simulation_id=123,
            payload={"message_id": 456, "content": "Hello"},
            idempotency_key="message.item.created:456",
        )
    """
    from django.apps import apps

    OutboxEvent = apps.get_model("common", "OutboxEvent")
    canonical_event_type = event_types.canonical_event_type(event_type)
    if canonical_event_type != event_type:
        logger.info(
            "Canonicalized legacy outbox event type %s -> %s", event_type, canonical_event_type
        )
    event_type = canonical_event_type
    if not event_types.is_valid_canonical_event_type(event_type):
        raise ValueError(f"Invalid canonical outbox event type: {event_type}")
    payload = _normalize_payload(payload)

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
) -> OutboxEvent | None:
    """Synchronous version of enqueue_event.

    Use this when calling from synchronous code (e.g., Django signals).
    """
    from django.apps import apps

    OutboxEvent = apps.get_model("common", "OutboxEvent")
    canonical_event_type = event_types.canonical_event_type(event_type)
    if canonical_event_type != event_type:
        logger.info(
            "Canonicalized legacy outbox event type %s -> %s", event_type, canonical_event_type
        )
    event_type = canonical_event_type
    if not event_types.is_valid_canonical_event_type(event_type):
        raise ValueError(f"Invalid canonical outbox event type: {event_type}")
    payload = _normalize_payload(payload)

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


def build_canonical_envelope(
    event: OutboxEvent,
    *,
    enrich_payload: Any | None = None,
) -> dict[str, Any]:
    """Build a canonical transport envelope from an OutboxEvent.

    This is the **single** envelope builder for all transports (REST catch-up,
    SSE streaming, and WebSocket delivery).  It uses the ``EventEnvelope``
    Pydantic model so datetime serialization is identical everywhere.

    Args:
        event: The OutboxEvent to convert.
        enrich_payload: Optional callable ``(payload: dict) -> dict`` that
            returns an enriched copy of the payload (e.g. to inject resolved
            media URLs).  The original outbox payload is never mutated.

    Returns:
        A JSON-safe dict matching the ``EventEnvelope`` schema.
    """
    from api.v1.schemas.events import EventEnvelope

    payload = dict(event.payload or {})
    if enrich_payload is not None:
        payload = enrich_payload(payload)

    envelope = EventEnvelope(
        event_id=str(event.id),
        event_type=event.event_type,
        created_at=event.created_at or datetime.now(UTC),
        correlation_id=event.correlation_id,
        payload=payload,
    )
    return envelope.model_dump(mode="json")


def build_ws_envelope(event: OutboxEvent) -> dict[str, Any]:
    """Build a WebSocket event envelope from an OutboxEvent.

    Delegates to :func:`build_canonical_envelope` so that all transports
    produce identical envelope shapes.
    """
    return build_canonical_envelope(event)


def order_outbox_queryset(queryset):
    """Apply the canonical deterministic ordering for outbox pagination."""
    return queryset.order_by("created_at", "id")


def filter_replayable_outbox_queryset(queryset):
    """Restrict a queryset to replayable ChatLab durable events."""
    return queryset.filter(event_type__in=event_types.canonical_event_types())


def apply_outbox_cursor(queryset, cursor_event):
    """Return rows strictly after ``cursor_event`` using a stable tie-breaker."""
    return queryset.filter(
        Q(created_at__gt=cursor_event.created_at)
        | Q(created_at=cursor_event.created_at, id__gt=cursor_event.id)
    )


def get_latest_cursor_sync(
    simulation_id: int,
    *,
    event_type_prefix: str | None = None,
) -> str | None:
    """Return the ID of the most recent outbox event for a simulation.

    The returned value is suitable for passing as the ``cursor`` parameter
    to the SSE stream endpoint so the client starts in **tail-only** mode
    (only events created *after* this point will be delivered).

    Returns ``None`` when no events exist for the simulation.
    """
    from django.apps import apps

    OutboxEventModel = apps.get_model("common", "OutboxEvent")
    qs = OutboxEventModel.objects.filter(simulation_id=simulation_id)
    if event_type_prefix:
        qs = qs.filter(event_type__startswith=event_type_prefix)
    qs = order_outbox_queryset(qs)
    latest = qs.last()
    return str(latest.id) if latest else None


async def get_latest_cursor(
    simulation_id: int,
    *,
    event_type_prefix: str | None = None,
) -> str | None:
    """Async version of :func:`get_latest_cursor_sync`."""

    @sync_to_async
    def _query():
        return get_latest_cursor_sync(simulation_id, event_type_prefix=event_type_prefix)

    return await _query()


def get_latest_event_id_sync(
    simulation_id: int,
    *,
    event_type_prefix: str | None = None,
) -> str | None:
    """Return the newest replayable ChatLab durable event ID for a simulation."""
    from django.apps import apps

    OutboxEventModel = apps.get_model("common", "OutboxEvent")
    qs = filter_replayable_outbox_queryset(
        OutboxEventModel.objects.filter(simulation_id=simulation_id)
    )
    if event_type_prefix:
        qs = qs.filter(event_type__startswith=event_type_prefix)
    qs = order_outbox_queryset(qs)
    latest = qs.last()
    return str(latest.id) if latest else None


async def get_latest_event_id(
    simulation_id: int,
    *,
    event_type_prefix: str | None = None,
) -> str | None:
    """Async version of :func:`get_latest_event_id_sync`."""

    return await get_latest_cursor(simulation_id, event_type_prefix=event_type_prefix)


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
) -> tuple[list[OutboxEvent], str | None, bool]:
    """Get events for a simulation (catch-up endpoint).

    This allows clients to fetch missed events after reconnection.

    Args:
        simulation_id: Simulation to get events for
        cursor: Event ID to start after (exclusive)
        limit: Maximum number of events to return

    Returns:
        Tuple of (events, next_cursor, has_more)
    """
    from django.apps import apps

    OutboxEvent = apps.get_model("common", "OutboxEvent")

    @sync_to_async
    def _query():
        queryset = order_outbox_queryset(
            OutboxEvent.objects.filter(
                simulation_id=simulation_id,
            )
        )

        if cursor:
            try:
                cursor_uuid = uuid.UUID(cursor)
                # Get the created_at of the cursor event
                try:
                    cursor_event = OutboxEvent.objects.get(
                        id=cursor_uuid,
                        simulation_id=simulation_id,
                    )
                    queryset = apply_outbox_cursor(queryset, cursor_event)
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


def get_outbox_event_sync(
    *,
    simulation_id: int,
    event_id: uuid.UUID,
) -> OutboxEvent | None:
    """Return a durable outbox event for a simulation by ID."""
    from django.apps import apps

    OutboxEvent = apps.get_model("common", "OutboxEvent")
    return (
        OutboxEvent.objects.filter(
            simulation_id=simulation_id,
            id=event_id,
        )
        .order_by()
        .first()
    )


def get_replayable_outbox_event_sync(
    *,
    simulation_id: int,
    event_id: uuid.UUID,
) -> OutboxEvent | None:
    """Return a replayable durable outbox event for a simulation by ID."""
    from django.apps import apps

    OutboxEvent = apps.get_model("common", "OutboxEvent")
    return (
        filter_replayable_outbox_queryset(
            OutboxEvent.objects.filter(
                simulation_id=simulation_id,
                id=event_id,
            )
        )
        .order_by()
        .first()
    )


async def get_outbox_event(
    *,
    simulation_id: int,
    event_id: uuid.UUID,
) -> OutboxEvent | None:
    """Async wrapper for :func:`get_outbox_event_sync`."""

    return await sync_to_async(get_outbox_event_sync)(
        simulation_id=simulation_id,
        event_id=event_id,
    )


async def get_replayable_outbox_event(
    *,
    simulation_id: int,
    event_id: uuid.UUID,
) -> OutboxEvent | None:
    """Async wrapper for :func:`get_replayable_outbox_event_sync`."""

    return await sync_to_async(get_replayable_outbox_event_sync)(
        simulation_id=simulation_id,
        event_id=event_id,
    )


def get_events_after_event_sync(
    *,
    simulation_id: int,
    last_event_id: uuid.UUID | None = None,
) -> list[OutboxEvent]:
    """Return replayable durable events strictly after ``last_event_id`` in canonical order."""
    from django.apps import apps

    OutboxEvent = apps.get_model("common", "OutboxEvent")
    queryset = order_outbox_queryset(
        filter_replayable_outbox_queryset(OutboxEvent.objects.filter(simulation_id=simulation_id))
    )
    if last_event_id is None:
        return list(queryset)

    anchor_event = get_replayable_outbox_event_sync(
        simulation_id=simulation_id,
        event_id=last_event_id,
    )
    if anchor_event is None:
        return []

    return list(apply_outbox_cursor(queryset, anchor_event))


async def get_events_after_event(
    *,
    simulation_id: int,
    last_event_id: uuid.UUID | None = None,
) -> list[OutboxEvent]:
    """Async wrapper for :func:`get_events_after_event_sync`."""

    return await sync_to_async(get_events_after_event_sync)(
        simulation_id=simulation_id,
        last_event_id=last_event_id,
    )
