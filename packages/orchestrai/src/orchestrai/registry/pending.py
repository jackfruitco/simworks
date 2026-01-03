"""Queue for registration records created before an app is active."""

from __future__ import annotations

from threading import RLock
from typing import Iterable

from .records import RegistrationRecord


class PendingRegistrations:
    """Thread-safe queue of pending component registrations."""

    def __init__(self) -> None:
        self._records: list[RegistrationRecord] = []
        self._lock = RLock()

    def enqueue(self, record: RegistrationRecord) -> None:
        with self._lock:
            self._records.append(record)

    def extend(self, records: Iterable[RegistrationRecord]) -> None:
        with self._lock:
            self._records.extend(records)

    def flush_into(self, store) -> None:
        from .component_store import ComponentStore

        if not isinstance(store, ComponentStore):
            raise TypeError("flush_into expects a ComponentStore instance")

        with self._lock:
            records = tuple(self._records)
            self._records.clear()

        for record in records:
            store.register(record)

    def snapshot(self) -> tuple[RegistrationRecord, ...]:
        with self._lock:
            return tuple(self._records)


__all__ = ["PendingRegistrations"]
