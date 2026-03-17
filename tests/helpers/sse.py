"""Helpers for consuming SSE streaming responses in tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync

if TYPE_CHECKING:
    from django.http import StreamingHttpResponse


def decode_chunk(chunk: bytes | str) -> str:
    return chunk.decode() if isinstance(chunk, bytes) else chunk


def collect_streaming_chunks(response: StreamingHttpResponse, n: int) -> list[str]:
    """Collect *n* chunks from a StreamingHttpResponse (sync or async).

    Uses ``async_to_sync`` to consume async generators so that sync
    test methods can call this without becoming async themselves.
    ``async_to_sync`` re-uses the Django-managed single-threaded executor
    which avoids SQLite "table locked" errors from cross-thread access.
    """
    streaming = response.streaming_content

    if hasattr(streaming, "__aiter__"):

        async def _gather():
            chunks: list[str] = []
            async for raw in streaming:
                chunks.append(decode_chunk(raw))
                if len(chunks) >= n:
                    break
            return chunks

        return async_to_sync(_gather)()

    # Sync fallback
    from itertools import islice

    return [decode_chunk(c) for c in islice(streaming, n)]
