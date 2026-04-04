"""Regression tests for the hardened event-delivery contract.

Covers:
A. Transport parity — canonical envelope is identical across REST / SSE / WS.
B. Tail-only live connect — SSE with no cursor does not replay history.
C. Resume semantics — SSE with cursor=X delivers only events after X.
D. Stale cursor — SSE returns error frame with status 410.
E. Explicit replay — SSE with replay=True streams from the beginning.
F. Bootstrap checkpoint — state response includes a usable cursor.
G. Duplicate-tolerant semantics — event identity is stable.
H. Media payload completeness across transports.
"""

from __future__ import annotations

import json
import uuid

from asgiref.sync import sync_to_async
import pytest

from api.v1.sse import resolve_outbox_stream_anchor, stream_outbox_events
from apps.common.models import OutboxEvent
from apps.common.outbox.event_types import (
    MESSAGE_CREATED,
    SIMULATION_STATUS_UPDATED,
)
from apps.common.outbox.outbox import (
    build_canonical_envelope,
    build_ws_envelope,
    get_latest_cursor,
    get_latest_cursor_sync,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    chunks: list[str] = []
    async for chunk in streaming_content:
        chunks.append(decode_chunk(chunk))
        if len(chunks) >= n:
            break
    return chunks


def collect_data_payloads(chunks: list[str]) -> list[dict]:
    """Extract parsed JSON payloads from SSE ``data:`` lines."""
    payloads = []
    for chunk in chunks:
        if chunk.startswith("data: "):
            raw = chunk[len("data: ") :].strip()
            if raw:
                payloads.append(json.loads(raw))
    return payloads


_stream = sync_to_async(stream_outbox_events, thread_sensitive=False)


# ---------------------------------------------------------------------------
# A. Transport parity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTransportParity:
    """Canonical envelope must be identical across all transports."""

    def test_canonical_and_ws_envelope_are_identical(self):
        """build_canonical_envelope and build_ws_envelope produce the same dict."""
        event = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=42,
            payload={"status": "running", "phase": "running"},
            idempotency_key=f"parity:{uuid.uuid4()}",
            correlation_id="corr-123",
        )
        canonical = build_canonical_envelope(event)
        ws = build_ws_envelope(event)
        assert canonical == ws

    def test_envelope_has_required_fields(self):
        event = OutboxEvent.objects.create(
            event_type=MESSAGE_CREATED,
            simulation_id=1,
            payload={"message_id": 1, "content": "hello"},
            idempotency_key=f"fields:{uuid.uuid4()}",
        )
        envelope = build_canonical_envelope(event)
        assert set(envelope.keys()) == {
            "event_id",
            "event_type",
            "created_at",
            "correlation_id",
            "payload",
        }
        assert envelope["event_id"] == str(event.id)
        assert envelope["event_type"] == MESSAGE_CREATED

    def test_created_at_is_iso_string(self):
        event = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=1,
            payload={"status": "seeded"},
            idempotency_key=f"ts:{uuid.uuid4()}",
        )
        envelope = build_canonical_envelope(event)
        # Must be a string, not a datetime
        assert isinstance(envelope["created_at"], str)
        # Must be parseable ISO 8601
        from datetime import datetime

        datetime.fromisoformat(envelope["created_at"])

    def test_enrich_payload_callback(self):
        event = OutboxEvent.objects.create(
            event_type=MESSAGE_CREATED,
            simulation_id=1,
            payload={"message_id": 99},
            idempotency_key=f"enrich:{uuid.uuid4()}",
        )
        enriched = build_canonical_envelope(
            event,
            enrich_payload=lambda p: {**p, "media_list": [{"id": 1}]},
        )
        assert enriched["payload"]["media_list"] == [{"id": 1}]
        # Original event payload not mutated
        assert "media_list" not in event.payload


# ---------------------------------------------------------------------------
# B. Tail-only live connect
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTailOnlyLiveConnect:
    """SSE with no cursor must NOT replay historical events."""

    @pytest.mark.asyncio
    async def test_nil_cursor_skips_existing_events(self, monkeypatch):
        """Connecting without a cursor should not deliver pre-existing events."""
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        # Create historical events BEFORE connecting
        for i in range(3):
            await OutboxEvent.objects.acreate(
                event_type=SIMULATION_STATUS_UPDATED,
                simulation_id=50,
                payload={"index": i},
                idempotency_key=f"tail-hist:{i}:{uuid.uuid4()}",
            )

        response = await _stream(
            simulation_id=50,
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        # Collect several chunks — should be heartbeats only
        chunks = await collect_chunks(response.streaming_content, 3)
        for chunk in chunks:
            assert chunk == ": keep-alive\n\n", f"Expected heartbeat, got event data: {chunk!r}"


# ---------------------------------------------------------------------------
# C. Resume semantics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResumeSemantics:
    """SSE with cursor=X must deliver only events after X."""

    @pytest.mark.asyncio
    async def test_cursor_resumes_after_specified_event(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        events = []
        for i in range(3):
            e = await OutboxEvent.objects.acreate(
                event_type=SIMULATION_STATUS_UPDATED,
                simulation_id=51,
                payload={"index": i},
                idempotency_key=f"resume:{i}:{uuid.uuid4()}",
            )
            events.append(e)

        # Resume after the first event — should get events[1] and events[2]
        response = await _stream(
            simulation_id=51,
            cursor=str(events[0].id),
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        chunks: list[str] = []
        async for chunk in response.streaming_content:
            decoded = decode_chunk(chunk)
            if decoded == ": keep-alive\n\n":
                if chunks:
                    break
                continue
            chunks.append(decoded)
            if len(chunks) >= 6:  # 2 events x 3 lines each
                break

        payloads = collect_data_payloads(chunks)
        assert len(payloads) == 2
        assert payloads[0]["payload"]["index"] == 1
        assert payloads[1]["payload"]["index"] == 2


# ---------------------------------------------------------------------------
# D. Stale cursor → HTTP 410
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStaleCursor:
    """Stale/missing cursor must raise HTTP 410 before any stream bytes are sent."""

    def test_stale_cursor_raises_http_410(self):
        """A valid UUID that doesn't exist in the DB raises HttpError(410)."""
        from ninja.errors import HttpError

        fake_cursor = str(uuid.uuid4())
        with pytest.raises(HttpError) as exc_info:
            resolve_outbox_stream_anchor(
                simulation_id=60,
                cursor=fake_cursor,
            )

        assert exc_info.value.status_code == 410
        assert "stale" in str(exc_info.value.message).lower() or "re-bootstrap" in str(
            exc_info.value.message
        ).lower()

    def test_stale_cursor_raises_before_stream_opens(self):
        """stream_outbox_events raises 410 before returning StreamingHttpResponse."""
        from ninja.errors import HttpError

        fake_cursor = str(uuid.uuid4())
        with pytest.raises(HttpError) as exc_info:
            stream_outbox_events(
                simulation_id=60,
                cursor=fake_cursor,
                heartbeat_interval_seconds=10.0,
            )

        assert exc_info.value.status_code == 410


# ---------------------------------------------------------------------------
# E. Explicit replay
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExplicitReplay:
    """replay=True with no cursor must stream from the beginning."""

    @pytest.mark.asyncio
    async def test_replay_true_delivers_all_events(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        for i in range(3):
            await OutboxEvent.objects.acreate(
                event_type=SIMULATION_STATUS_UPDATED,
                simulation_id=70,
                payload={"index": i},
                idempotency_key=f"replay:{i}:{uuid.uuid4()}",
            )

        response = await _stream(
            simulation_id=70,
            replay=True,
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        chunks: list[str] = []
        async for chunk in response.streaming_content:
            decoded = decode_chunk(chunk)
            if decoded == ": keep-alive\n\n":
                if chunks:
                    break
                continue
            chunks.append(decoded)
            if len(chunks) >= 9:  # 3 events x 3 lines
                break

        payloads = collect_data_payloads(chunks)
        assert len(payloads) == 3
        assert payloads[0]["payload"]["index"] == 0
        assert payloads[1]["payload"]["index"] == 1
        assert payloads[2]["payload"]["index"] == 2


# ---------------------------------------------------------------------------
# F. Bootstrap checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBootstrapCheckpoint:
    """get_latest_cursor must return the ID of the newest outbox event."""

    def test_latest_cursor_sync_returns_last_event_id(self):
        events = []
        for i in range(3):
            events.append(
                OutboxEvent.objects.create(
                    event_type=SIMULATION_STATUS_UPDATED,
                    simulation_id=80,
                    payload={"index": i},
                    idempotency_key=f"checkpoint:{i}:{uuid.uuid4()}",
                )
            )
        cursor = get_latest_cursor_sync(80)
        assert cursor == str(events[-1].id)

    def test_latest_cursor_sync_returns_none_when_empty(self):
        cursor = get_latest_cursor_sync(999999)
        assert cursor is None

    @pytest.mark.asyncio
    async def test_latest_cursor_async(self):
        event = await OutboxEvent.objects.acreate(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=81,
            payload={"status": "seeded"},
            idempotency_key=f"async-cursor:{uuid.uuid4()}",
        )
        cursor = await get_latest_cursor(81)
        assert cursor == str(event.id)

    @pytest.mark.asyncio
    async def test_checkpoint_safe_resume(self, monkeypatch):
        """Connecting SSE with the bootstrap checkpoint should not replay."""
        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        for i in range(3):
            await OutboxEvent.objects.acreate(
                event_type=SIMULATION_STATUS_UPDATED,
                simulation_id=82,
                payload={"index": i},
                idempotency_key=f"safe-resume:{i}:{uuid.uuid4()}",
            )

        checkpoint = await get_latest_cursor(82)
        assert checkpoint is not None

        response = await _stream(
            simulation_id=82,
            cursor=checkpoint,
            heartbeat_interval_seconds=10.0,
            poll_interval_seconds=1.0,
        )

        # Should get only heartbeats — no replayed events
        chunks = await collect_chunks(response.streaming_content, 3)
        for chunk in chunks:
            assert chunk == ": keep-alive\n\n"

    def test_latest_cursor_respects_event_type_prefix(self):
        OutboxEvent.objects.create(
            event_type=MESSAGE_CREATED,
            simulation_id=83,
            payload={"message_id": 1},
            idempotency_key=f"prefix-msg:{uuid.uuid4()}",
        )
        sim_event = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=83,
            payload={"status": "running"},
            idempotency_key=f"prefix-sim:{uuid.uuid4()}",
        )
        cursor = get_latest_cursor_sync(83, event_type_prefix="simulation.")
        assert cursor == str(sim_event.id)


# ---------------------------------------------------------------------------
# G. Duplicate-tolerant semantics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDuplicateTolerant:
    """Event identity must be deterministic from the outbox row."""

    def test_same_event_produces_stable_identity(self):
        event = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=90,
            payload={"status": "running"},
            idempotency_key=f"stable:{uuid.uuid4()}",
        )
        env1 = build_canonical_envelope(event)
        env2 = build_canonical_envelope(event)
        assert env1 == env2
        assert env1["event_id"] == str(event.id)

    def test_different_events_have_different_identities(self):
        e1 = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=91,
            payload={"status": "running"},
            idempotency_key=f"diff-a:{uuid.uuid4()}",
        )
        e2 = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=91,
            payload={"status": "paused"},
            idempotency_key=f"diff-b:{uuid.uuid4()}",
        )
        assert build_canonical_envelope(e1)["event_id"] != build_canonical_envelope(e2)["event_id"]


# ---------------------------------------------------------------------------
# H. Media payload completeness (basic — without full Message model)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMediaPayloadCompleteness:
    """The canonical envelope must preserve the payload as-is from the outbox."""

    def test_message_event_payload_preserved(self):
        payload = {
            "message_id": 42,
            "content": "Hello world",
            "role": "A",
            "is_from_ai": True,
            "media_list": [
                {
                    "id": 1,
                    "uuid": "abc",
                    "original_url": "/img/1.png",
                    "thumbnail_url": "/img/1_t.png",
                }
            ],
            "mediaList": [
                {
                    "id": 1,
                    "uuid": "abc",
                    "original_url": "/img/1.png",
                    "thumbnail_url": "/img/1_t.png",
                }
            ],
        }
        event = OutboxEvent.objects.create(
            event_type=MESSAGE_CREATED,
            simulation_id=100,
            payload=payload,
            idempotency_key=f"media:{uuid.uuid4()}",
        )
        envelope = build_canonical_envelope(event)
        assert envelope["payload"]["media_list"] == payload["media_list"]
        assert envelope["payload"]["mediaList"] == payload["mediaList"]
        assert envelope["payload"]["content"] == "Hello world"
