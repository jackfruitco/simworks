"""Execution context enforcement helpers for ORM correctness."""

import asyncio


class _OrmModeError(RuntimeError):
    """Raised when code runs in an unexpected execution context."""


def must_be_async() -> None:
    """Ensure an asyncio loop is running for async ORM usage."""

    try:
        asyncio.get_running_loop()
    except RuntimeError as exc:  # pragma: no cover - exact exception type matters for message
        raise _OrmModeError("Async ORM requires an active event loop") from exc


def must_be_sync() -> None:
    """Ensure no asyncio loop is active for sync ORM usage."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise _OrmModeError("Sync ORM cannot run inside an active event loop")


__all__ = ["must_be_async", "must_be_sync"]
