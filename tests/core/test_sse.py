"""Tests for SSE streaming helper behavior."""

from datetime import timedelta
from itertools import islice
import uuid

from django.utils import timezone
from ninja.errors import HttpError
import pytest

from api.v1.sse import stream_outbox_events
from apps.common.models import OutboxEvent


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
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in islice(response.streaming_content, 4)
        ]

        assert chunks[0] == f"id: {second.id}\n"
        assert chunks[1] == "event: simulation\n"
        assert '"message_id": 2' in chunks[2]
        assert chunks[3] == ": keepalive\n\n"

    def test_invalid_cursor_returns_http_400(self):
        """Invalid cursor format is rejected."""
        with pytest.raises(HttpError) as exc_info:
            stream_outbox_events(simulation_id=1, cursor="not-a-uuid")

        assert getattr(exc_info.value, "status_code", None) == 400
