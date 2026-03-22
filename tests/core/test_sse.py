"""Tests for SSE streaming helper behavior."""

import asyncio
from datetime import timedelta
from itertools import pairwise
import uuid

from asgiref.sync import sync_to_async
from django.utils import timezone
from ninja.errors import HttpError
import pytest

from api.v1.sse import stream_outbox_events
from apps.common.models import OutboxEvent
from apps.common.outbox.event_types import MESSAGE_CREATED, SIMULATION_STATUS_UPDATED


class FakeClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += seconds


def decode_chunk(chunk) -> str:
    return chunk.decode() if isinstance(chunk, bytes) else chunk


async def collect_chunks(streaming_content, n: int) -> list[str]:
    """Collect *n* chunks from an async streaming iterator."""
    chunks: list[str] = []
    async for chunk in streaming_content:
        chunks.append(decode_chunk(chunk))
        if len(chunks) >= n:
            break
    return chunks


# Wrap the sync function so it runs in a thread (same as Django ASGI does
# for sync views), avoiding SynchronousOnlyOperation from the cursor lookup.
_stream = sync_to_async(stream_outbox_events, thread_sensitive=False)


@pytest.mark.django_db
class TestStreamOutboxEvents:
    """Regression tests for SSE cursor handling."""

    @pytest.mark.asyncio
    async def test_cursor_does_not_skip_same_timestamp_events(self, monkeypatch):
        """Events with same created_at as cursor are still streamed when id is greater."""
        shared_created_at = timezone.now() - timedelta(minutes=1)
        event_id_1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
        event_id_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")

        first = await OutboxEvent.objects.acreate(
            id=event_id_1,
            event_type=MESSAGE_CREATED,
            simulation_id=7,
            payload={"message_id": 1},
            idempotency_key="same-ts:1",
        )
        second = await OutboxEvent.objects.acreate(
            id=event_id_2,
            event_type=MESSAGE_CREATED,
            simulation_id=7,
            payload={"message_id": 2},
            idempotency_key="same-ts:2",
        )
        await OutboxEvent.objects.filter(id__in=[first.id, second.id]).aupdate(
            created_at=shared_created_at
        )

        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        response = await _stream(
            simulation_id=7,
            cursor=str(first.id),
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        chunks: list[str] = []
        async for chunk in response.streaming_content:
            decoded = decode_chunk(chunk)
            if decoded == ": keep-alive\n\n":
                continue
            chunks.append(decoded)
            if len(chunks) >= 3:
                break

        assert chunks[0] == f"id: {second.id}\n"
        assert chunks[1] == "event: simulation\n"
        assert '"message_id": 2' in chunks[2]

    @pytest.mark.asyncio
    async def test_idle_heartbeats_emit_keep_alive_comment_on_cadence(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        anchor = await OutboxEvent.objects.acreate(
            event_type="trainerlab.stream.anchor",
            simulation_id=99,
            payload={"seed": True},
            idempotency_key="trainerlab.anchor:test",
        )

        response = await _stream(
            simulation_id=99,
            cursor=str(anchor.id),
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        emission_times = []
        chunks = []
        async for chunk in response.streaming_content:
            chunks.append(decode_chunk(chunk))
            emission_times.append(clock.current)
            if len(chunks) >= 3:
                break

        assert chunks == [": keep-alive\n\n", ": keep-alive\n\n", ": keep-alive\n\n"]
        assert emission_times == pytest.approx([0.0, 10.0, 20.0])
        assert [b - a for a, b in pairwise(emission_times)] == pytest.approx([10.0, 10.0])

    @pytest.mark.asyncio
    async def test_events_reset_idle_heartbeat_timer(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        event = await OutboxEvent.objects.acreate(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=8,
            payload={"status": "seeded", "phase": "seeded"},
            idempotency_key="simulation.status.updated:seeded:test",
        )

        response = await _stream(
            simulation_id=8,
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        chunks = await collect_chunks(response.streaming_content, 5)

        assert chunks[0] == ": keep-alive\n\n"
        assert chunks[1] == f"id: {event.id}\n"
        assert chunks[2] == "event: simulation\n"
        assert f'"{SIMULATION_STATUS_UPDATED}"' in chunks[3]
        assert chunks[4] == ": keep-alive\n\n"
        assert clock.current == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_cancelled_disconnect_exits_cleanly(self, monkeypatch):
        async def _cancel_sleep(_seconds: float) -> None:
            raise asyncio.CancelledError

        debug_calls: list[tuple[str, dict]] = []
        exception_calls: list[tuple[str, dict]] = []
        info_calls: list[tuple[str, dict]] = []

        def _debug(message: str, **kwargs) -> None:
            debug_calls.append((message, kwargs))

        def _info(message: str, **kwargs) -> None:
            info_calls.append((message, kwargs))

        def _exception(message: str, **kwargs) -> None:
            exception_calls.append((message, kwargs))

        monkeypatch.setattr("api.v1.sse.asyncio.sleep", _cancel_sleep)
        monkeypatch.setattr("api.v1.sse.logger.debug", _debug)
        monkeypatch.setattr("api.v1.sse.logger.exception", _exception)
        monkeypatch.setattr("api.v1.sse.logger.info", _info)

        response = await _stream(
            simulation_id=123,
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        chunks = [decode_chunk(chunk) async for chunk in response.streaming_content]

        assert chunks == [": keep-alive\n\n"]
        assert ("sse_stream_closed", {"simulation_id": 123}) in info_calls
        assert exception_calls == []

    def test_invalid_cursor_returns_http_400(self):
        """Invalid cursor format is rejected."""
        with pytest.raises(HttpError) as exc_info:
            stream_outbox_events(simulation_id=1, cursor="not-a-uuid")

        assert getattr(exc_info.value, "status_code", None) == 400
