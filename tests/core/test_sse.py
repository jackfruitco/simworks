"""Tests for SSE streaming helper behavior."""

from datetime import timedelta
from itertools import islice
import uuid

from django.utils import timezone
from ninja.errors import HttpError
import pytest

from api.v1.sse import stream_outbox_events
from apps.common.models import OutboxEvent


class FakeClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds


def decode_chunk(chunk) -> str:
    return chunk.decode() if isinstance(chunk, bytes) else chunk


@pytest.mark.django_db
class TestStreamOutboxEvents:
    """Regression tests for SSE cursor handling."""

    def test_cursor_does_not_skip_same_timestamp_events(self, monkeypatch):
        """Events with same created_at as cursor are still streamed when id is greater."""
        shared_created_at = timezone.now() - timedelta(minutes=1)
        event_id_1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
        event_id_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")

        first = OutboxEvent.objects.create(
            id=event_id_1,
            event_type="message.created",
            simulation_id=7,
            payload={"message_id": 1},
            idempotency_key="same-ts:1",
        )
        second = OutboxEvent.objects.create(
            id=event_id_2,
            event_type="message.created",
            simulation_id=7,
            payload={"message_id": 2},
            idempotency_key="same-ts:2",
        )
        OutboxEvent.objects.filter(id__in=[first.id, second.id]).update(
            created_at=shared_created_at
        )

        monkeypatch.setattr("api.v1.sse.time.sleep", lambda _: None)

        response = stream_outbox_events(simulation_id=7, cursor=str(first.id))
        chunks = [
            decode_chunk(chunk) for chunk in islice(response.streaming_content, 4)
        ]

        assert chunks[0] == f"id: {second.id}\n"
        assert chunks[1] == "event: simulation\n"
        assert '"message_id": 2' in chunks[2]
        assert chunks[3] == ": keep-alive\n\n"

    def test_idle_heartbeats_emit_keep_alive_comment_on_cadence(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.time.sleep", clock.sleep)

        anchor = OutboxEvent.objects.create(
            event_type="trainerlab.stream.anchor",
            simulation_id=99,
            payload={"seed": True},
            idempotency_key="trainerlab.anchor:test",
        )

        response = stream_outbox_events(
            simulation_id=99,
            cursor=str(anchor.id),
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        stream_iter = iter(response.streaming_content)
        emission_times = []
        chunks = []
        for _ in range(3):
            chunks.append(decode_chunk(next(stream_iter)))
            emission_times.append(clock.current)

        assert chunks == [": keep-alive\n\n", ": keep-alive\n\n", ": keep-alive\n\n"]
        assert emission_times == pytest.approx([10.0, 20.0, 30.0])
        assert max(b - a for a, b in zip(emission_times, emission_times[1:])) <= 10.0

    def test_events_reset_idle_heartbeat_timer(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.time.sleep", clock.sleep)

        event = OutboxEvent.objects.create(
            event_type="trainerlab.session.seeded",
            simulation_id=8,
            payload={"status": "seeded"},
            idempotency_key="trainerlab.seeded:test",
        )

        response = stream_outbox_events(
            simulation_id=8,
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )
        stream_iter = iter(response.streaming_content)

        chunks = [decode_chunk(chunk) for chunk in islice(stream_iter, 3)]
        heartbeat = decode_chunk(next(stream_iter))

        assert chunks[0] == f"id: {event.id}\n"
        assert chunks[1] == "event: simulation\n"
        assert '"trainerlab.session.seeded"' in chunks[2]
        assert heartbeat == ": keep-alive\n\n"
        assert clock.current == pytest.approx(10.0)

    def test_invalid_cursor_returns_http_400(self):
        """Invalid cursor format is rejected."""
        with pytest.raises(HttpError) as exc_info:
            stream_outbox_events(simulation_id=1, cursor="not-a-uuid")

        assert getattr(exc_info.value, "status_code", None) == 400
