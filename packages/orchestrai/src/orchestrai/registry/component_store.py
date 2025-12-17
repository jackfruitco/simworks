# orchestrai/registry/component_store.py
"""Identity-indexed component registries owned by each app."""
from threading import RLock
from typing import Any

from .base import ComponentRegistry
from .records import RegistrationRecord


class ComponentStore:
    """Container managing component registries by kind."""

    def __init__(self) -> None:
        self._registries: dict[str, ComponentRegistry[Any]] = {}
        self._lock = RLock()

    def registry(self, kind: str) -> ComponentRegistry[Any]:
        key = str(kind).strip()
        if not key:
            raise ValueError("registry kind must be a non-empty string")

        with self._lock:
            if key not in self._registries:
                self._registries[key] = ComponentRegistry()
            return self._registries[key]

    def register(self, record: RegistrationRecord) -> None:
        registry = self.registry(record.kind)
        registry.register(record.component)

    def try_get(self, kind: str, ident: Any):
        return self.registry(kind).try_get(ident)

    def get(self, kind: str, ident: Any):
        return self.registry(kind).get(ident)

    def items(self) -> dict[str, ComponentRegistry[Any]]:
        with self._lock:
            return dict(self._registries)

    def kinds(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._registries.keys()))

    def freeze_all(self) -> None:
        for registry in self.items().values():
            registry.freeze()


__all__ = ["ComponentStore"]
