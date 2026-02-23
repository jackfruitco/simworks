"""Tests for outbox pattern implementation.

Tests that:
1. OutboxEvent model works correctly
2. enqueue_event creates events with idempotency
3. build_ws_envelope produces correct format
4. drain_outbox delivers events via channel layer
5. Concurrent drain safety (skip_locked)
"""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.common.models import OutboxEvent
from apps.common.outbox import (
    build_ws_envelope,
    enqueue_event,
    enqueue_event_sync,
    get_events_for_simulation,
)


@pytest.fixture
def outbox_event(db):
    """Create a test outbox event."""
    return OutboxEvent.objects.create(
        event_type="message.created",
        simulation_id=1,
        payload={"message_id": 123, "content": "Test message"},
        idempotency_key="message.created:123",
        correlation_id="test-correlation-id",
    )


@pytest.mark.django_db
class TestOutboxEventModel:
    """Tests for OutboxEvent model."""

    def test_create_outbox_event(self):
        """Can create an outbox event with required fields."""
        event = OutboxEvent.objects.create(
            event_type="message.created",
            simulation_id=1,
            payload={"message_id": 1},
            idempotency_key="test:1",
        )

        assert event.id is not None
        assert event.status == OutboxEvent.EventStatus.PENDING
        assert event.delivery_attempts == 0
        assert event.delivered_at is None
        assert event.created_at is not None

    def test_idempotency_key_unique(self):
        """Duplicate idempotency_key raises IntegrityError."""
        OutboxEvent.objects.create(
            event_type="message.created",
            simulation_id=1,
            payload={"message_id": 1},
            idempotency_key="unique:1",
        )

        with pytest.raises(IntegrityError):
            OutboxEvent.objects.create(
                event_type="message.created",
                simulation_id=2,
                payload={"message_id": 2},
                idempotency_key="unique:1",  # Same key
            )

    def test_mark_delivered(self, outbox_event):
        """mark_delivered updates status and delivered_at."""
        outbox_event.mark_delivered()

        assert outbox_event.status == OutboxEvent.EventStatus.DELIVERED
        assert outbox_event.delivered_at is not None

        # Verify persisted
        outbox_event.refresh_from_db()
        assert outbox_event.status == OutboxEvent.EventStatus.DELIVERED

    def test_mark_failed(self, outbox_event):
        """mark_failed updates status, attempts, and error."""
        outbox_event.mark_failed("Connection timeout")

        assert outbox_event.status == OutboxEvent.EventStatus.FAILED
        assert outbox_event.delivery_attempts == 1
        assert outbox_event.last_error == "Connection timeout"

        # Verify persisted
        outbox_event.refresh_from_db()
        assert outbox_event.status == OutboxEvent.EventStatus.FAILED

    def test_increment_attempts(self, outbox_event):
        """increment_attempts increases counter without changing status."""
        initial_status = outbox_event.status

        outbox_event.increment_attempts()

        assert outbox_event.delivery_attempts == 1
        assert outbox_event.status == initial_status

    def test_str_representation(self, outbox_event):
        """String representation is readable."""
        result = str(outbox_event)

        assert str(outbox_event.id) in result
        assert "message.created" in result
        assert "pending" in result


@pytest.mark.django_db
class TestEnqueueEvent:
    """Tests for enqueue_event functions."""

    def test_enqueue_event_sync_creates_event(self):
        """enqueue_event_sync creates an event."""
        event = enqueue_event_sync(
            event_type="simulation.ended",
            simulation_id=42,
            payload={"ended_at": "2024-01-01T12:00:00Z"},
            idempotency_key="simulation.ended:42",
            correlation_id="corr-123",
        )

        assert event is not None
        assert event.event_type == "simulation.ended"
        assert event.simulation_id == 42
        assert event.payload == {"ended_at": "2024-01-01T12:00:00Z"}
        assert event.idempotency_key == "simulation.ended:42"
        assert event.correlation_id == "corr-123"

    def test_enqueue_event_sync_generates_idempotency_key(self):
        """If no idempotency_key provided, one is generated."""
        event = enqueue_event_sync(
            event_type="test.event",
            simulation_id=1,
            payload={},
        )

        assert event is not None
        assert event.idempotency_key.startswith("test.event:")

    def test_enqueue_event_sync_returns_none_for_duplicate(self):
        """Duplicate idempotency_key returns None."""
        enqueue_event_sync(
            event_type="test.event",
            simulation_id=1,
            payload={},
            idempotency_key="dup:1",
        )

        result = enqueue_event_sync(
            event_type="test.event",
            simulation_id=1,
            payload={},
            idempotency_key="dup:1",  # Same key
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_enqueue_event_async_creates_event(self):
        """Async enqueue_event creates an event."""
        event = await enqueue_event(
            event_type="async.test",
            simulation_id=99,
            payload={"async": True},
            idempotency_key="async:99",
        )

        assert event is not None
        assert event.event_type == "async.test"
        assert event.simulation_id == 99

    @pytest.mark.asyncio
    async def test_enqueue_event_async_returns_none_for_duplicate(self):
        """Async duplicate returns None."""
        await enqueue_event(
            event_type="async.dup",
            simulation_id=1,
            payload={},
            idempotency_key="async.dup:1",
        )

        result = await enqueue_event(
            event_type="async.dup",
            simulation_id=1,
            payload={},
            idempotency_key="async.dup:1",
        )

        assert result is None


@pytest.mark.django_db
class TestBuildWSEnvelope:
    """Tests for build_ws_envelope function."""

    def test_envelope_has_required_fields(self, outbox_event):
        """Envelope contains all required fields."""
        envelope = build_ws_envelope(outbox_event)

        assert "event_id" in envelope
        assert "event_type" in envelope
        assert "created_at" in envelope
        assert "correlation_id" in envelope
        assert "payload" in envelope

    def test_envelope_values_match_event(self, outbox_event):
        """Envelope values match the source event."""
        envelope = build_ws_envelope(outbox_event)

        assert envelope["event_id"] == str(outbox_event.id)
        assert envelope["event_type"] == outbox_event.event_type
        assert envelope["correlation_id"] == outbox_event.correlation_id
        assert envelope["payload"] == outbox_event.payload

    def test_envelope_created_at_is_iso_format(self, outbox_event):
        """created_at is in ISO 8601 format."""
        envelope = build_ws_envelope(outbox_event)

        # Should be parseable as ISO format
        from datetime import datetime

        datetime.fromisoformat(envelope["created_at"].replace("Z", "+00:00"))


@pytest.mark.django_db
class TestGetEventsForSimulation:
    """Tests for catch-up endpoint helper."""

    @pytest.mark.asyncio
    async def test_returns_events_for_simulation(self):
        """Returns events for the specified simulation."""
        # Create events for different simulations using async version
        await enqueue_event("event1", 100, {"n": 1}, "e1:100")
        await enqueue_event("event2", 100, {"n": 2}, "e2:100")
        await enqueue_event("event3", 200, {"n": 3}, "e3:200")  # Different sim

        events, _, _ = await get_events_for_simulation(100)

        assert len(events) == 2
        assert all(e.simulation_id == 100 for e in events)

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        """Respects limit parameter."""
        for i in range(5):
            await enqueue_event(f"event{i}", 101, {"n": i}, f"e{i}:101")

        events, next_cursor, has_more = await get_events_for_simulation(101, limit=2)

        assert len(events) == 2
        assert has_more is True
        assert next_cursor is not None

    @pytest.mark.asyncio
    async def test_cursor_pagination(self):
        """Cursor-based pagination works."""
        for i in range(5):
            await enqueue_event(f"event{i}", 102, {"n": i}, f"e{i}:102")

        # Get first page
        events1, cursor, _ = await get_events_for_simulation(102, limit=2)

        # Get second page using cursor
        events2, _, _ = await get_events_for_simulation(102, cursor=cursor, limit=2)

        # No overlap
        ids1 = {e.id for e in events1}
        ids2 = {e.id for e in events2}
        assert not ids1 & ids2

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_events(self):
        """Returns empty list when no events exist."""
        events, next_cursor, has_more = await get_events_for_simulation(999)

        assert events == []
        assert next_cursor is None
        assert has_more is False


@pytest.mark.django_db
class TestDrainOutbox:
    """Tests for drain_outbox task."""

    @pytest.fixture(autouse=True)
    def clear_outbox(self):
        """Clear all outbox events before each test."""
        OutboxEvent.objects.all().delete()

    @patch("channels.layers.get_channel_layer")
    def test_drain_delivers_pending_events(self, mock_get_channel_layer):
        """Drain delivers pending events to channel layer."""
        from apps.common.tasks import drain_outbox

        # Create mock channel layer with async group_send
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()  # Make group_send awaitable
        mock_get_channel_layer.return_value = mock_channel_layer

        # Create pending events
        event = enqueue_event_sync(
            "test.drain",
            300,
            {"test": True},
            "drain:300",
        )

        # Run drain
        drain_outbox()

        # Verify channel layer was used
        mock_channel_layer.group_send.assert_called()

        # Verify event was marked delivered
        event.refresh_from_db()
        assert event.status == OutboxEvent.EventStatus.DELIVERED

    @patch("channels.layers.get_channel_layer")
    def test_drain_skips_already_delivered(self, mock_get_channel_layer):
        """Drain skips already delivered events."""
        from apps.common.tasks import drain_outbox

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer

        # Create and mark as delivered
        event = enqueue_event_sync(
            "test.skip",
            301,
            {"test": True},
            "skip:301",
        )
        event.mark_delivered()

        # Run drain
        drain_outbox()

        # Channel layer should not be called (no pending events)
        mock_channel_layer.group_send.assert_not_called()

    @patch("channels.layers.get_channel_layer")
    def test_drain_increments_attempts_on_failure(self, mock_get_channel_layer):
        """Drain increments attempts when delivery fails."""
        from apps.common.tasks import drain_outbox

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send.side_effect = Exception("Connection failed")
        mock_get_channel_layer.return_value = mock_channel_layer

        # Create pending event
        event = enqueue_event_sync(
            "test.fail",
            302,
            {"test": True},
            "fail:302",
        )

        # Run drain
        drain_outbox()

        # Verify attempts incremented
        event.refresh_from_db()
        assert event.delivery_attempts == 1
        assert event.status == OutboxEvent.EventStatus.PENDING  # Not failed yet

    @patch("channels.layers.get_channel_layer")
    def test_drain_marks_failed_after_max_attempts(self, mock_get_channel_layer):
        """Drain marks event as failed after max attempts."""
        from apps.common.tasks import drain_outbox, DRAIN_MAX_ATTEMPTS

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send.side_effect = Exception("Connection failed")
        mock_get_channel_layer.return_value = mock_channel_layer

        # Create event at max-1 attempts
        event = enqueue_event_sync(
            "test.maxfail",
            303,
            {"test": True},
            "maxfail:303",
        )
        event.delivery_attempts = DRAIN_MAX_ATTEMPTS - 1
        event.save()

        # Run drain
        drain_outbox()

        # Verify marked as failed
        event.refresh_from_db()
        assert event.status == OutboxEvent.EventStatus.FAILED

    @patch("channels.layers.get_channel_layer")
    def test_drain_handles_no_channel_layer(self, mock_get_channel_layer):
        """Drain handles missing channel layer gracefully."""
        from apps.common.tasks import drain_outbox

        mock_get_channel_layer.return_value = None
        # Should not raise
        drain_outbox()


@pytest.mark.django_db
class TestCleanupDeliveredEvents:
    """Tests for cleanup_delivered_events task."""

    def test_cleanup_deletes_old_delivered_events(self):
        """Cleanup deletes events delivered more than N days ago."""
        from apps.common.tasks import cleanup_delivered_events

        # Create old delivered event
        old_event = enqueue_event_sync(
            "old.event",
            400,
            {},
            "old:400",
        )
        old_event.mark_delivered()
        old_event.delivered_at = timezone.now() - timedelta(days=10)
        old_event.save()

        # Create recent delivered event
        recent_event = enqueue_event_sync(
            "recent.event",
            401,
            {},
            "recent:401",
        )
        recent_event.mark_delivered()

        # Run cleanup with 7 days
        cleanup_delivered_events(days_old=7)

        # Old event should be deleted
        assert not OutboxEvent.objects.filter(id=old_event.id).exists()

        # Recent event should remain
        assert OutboxEvent.objects.filter(id=recent_event.id).exists()

    def test_cleanup_preserves_pending_events(self):
        """Cleanup does not delete pending events."""
        from apps.common.tasks import cleanup_delivered_events

        # Create old pending event
        event = enqueue_event_sync(
            "pending.event",
            402,
            {},
            "pending:402",
        )

        cleanup_delivered_events(days_old=0)  # Would delete all delivered

        # Pending event should remain
        assert OutboxEvent.objects.filter(id=event.id).exists()


@pytest.mark.django_db
class TestRetryFailedEvents:
    """Tests for retry_failed_events task."""

    def test_retry_resets_failed_events(self):
        """Retry resets failed events to pending."""
        from apps.common.tasks import retry_failed_events

        # Create failed event
        event = enqueue_event_sync(
            "failed.event",
            500,
            {},
            "failed:500",
        )
        event.mark_failed("Test error")

        # Run retry
        retry_failed_events()

        # Should be pending again
        event.refresh_from_db()
        assert event.status == OutboxEvent.EventStatus.PENDING

    def test_retry_preserves_attempt_count(self):
        """Retry preserves the attempt count."""
        from apps.common.tasks import retry_failed_events

        event = enqueue_event_sync(
            "retry.event",
            501,
            {},
            "retry:501",
        )
        event.delivery_attempts = 5
        event.mark_failed("Test error")
        # mark_failed increments delivery_attempts by 1, so it's now 6

        retry_failed_events()

        event.refresh_from_db()
        assert event.delivery_attempts == 6  # Preserved (5 + 1 from mark_failed)

    def test_retry_skips_old_failed_events(self):
        """Retry skips events that failed more than 24 hours ago."""
        from apps.common.tasks import retry_failed_events

        # Create old failed event
        event = enqueue_event_sync(
            "old.failed",
            502,
            {},
            "oldfailed:502",
        )
        event.mark_failed("Old error")
        # Manually set created_at to old date
        OutboxEvent.objects.filter(id=event.id).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        retry_failed_events()

        event.refresh_from_db()
        assert event.status == OutboxEvent.EventStatus.FAILED  # Not reset
