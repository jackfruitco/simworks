"""Small registry used by the Celery-like app lifecycle."""

from __future__ import annotations

from threading import RLock
from typing import Any, Dict, Iterable, Iterator


class Registry:
    def __init__(self) -> None:
        self._items: Dict[str, Any] = {}
        self._lock = RLock()
        self._frozen = False

    def register(self, name: str, obj: Any) -> None:
        with self._lock:
            if self._frozen:
                raise RuntimeError("Registry is frozen")
            if name not in self._items:
                self._items[name] = obj

    def get(self, name: str) -> Any:
        with self._lock:
            return self._items[name]

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._items)

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._items

    def __iter__(self) -> Iterator[tuple[str, Any]]:  # pragma: no cover - convenience
        return iter(self._items.items())

