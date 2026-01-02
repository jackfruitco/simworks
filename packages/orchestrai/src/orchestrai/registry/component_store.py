# orchestrai/registry/component_store.py
"""Identity-indexed component registries owned by each app."""
from threading import RLock
from typing import Any

from orchestrai.identity.domains import PERSIST_DOMAIN, SERVICES_DOMAIN

from .base import ComponentRegistry
from .records import RegistrationRecord


class ComponentStore:
    """Container managing component registries by domain."""

    def __init__(self) -> None:
        self._registries: dict[str, ComponentRegistry[Any]] = {}
        self._lock = RLock()

    def registry(self, domain: str) -> ComponentRegistry[Any]:
        key = str(domain).strip()
        if not key:
            raise ValueError("registry domain must be a non-empty string")

        with self._lock:
            if key not in self._registries:
                if key == SERVICES_DOMAIN:
                    from orchestrai.registry.services import ServiceRegistry

                    self._registries[key] = ServiceRegistry()
                else:
                    self._registries[key] = ComponentRegistry()
            return self._registries[key]

    def set_registry(
        self,
        domain: str,
        registry: ComponentRegistry[Any],
        *,
        replace: bool = False,
    ) -> ComponentRegistry[Any]:
        """Mount a concrete registry instance for a domain.

        If a registry already exists and ``replace`` is False, the existing registry
        is returned unchanged. When ``replace`` is True, the registry is swapped out
        only if the existing registry is empty; otherwise a ``ValueError`` is raised
        to avoid losing registrations.
        """

        key = str(domain).strip()
        if not key:
            raise ValueError("registry domain must be a non-empty string")
        if not isinstance(registry, ComponentRegistry):
            raise TypeError("registry must be a ComponentRegistry instance")

        with self._lock:
            existing = self._registries.get(key)
            if existing is registry:
                return registry
            if existing and not replace:
                return existing
            if existing and existing.count():
                raise ValueError(
                    f"cannot replace populated registry for domain {key!r}; "
                    "clear it first or supply an empty registry"
                )

            self._registries[key] = registry
            return registry

    def register(self, record: RegistrationRecord) -> None:
        registry = self.registry(record.domain)
        registry.register(record.component)

    def try_get(self, domain: str, ident: Any):
        return self.registry(domain).try_get(ident)

    def get(self, domain: str, ident: Any):
        return self.registry(domain).get(ident)

    def items(self) -> dict[str, ComponentRegistry[Any]]:
        with self._lock:
            return dict(self._registries)

    def domains(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._registries.keys()))

    # Backward-compatible alias
    def kinds(self) -> tuple[str, ...]:
        return self.domains()

    def freeze_all(self) -> None:
        for registry in self.items().values():
            registry.freeze()

    # Convenience aliases for persistence handlers
    @property
    def persist(self) -> ComponentRegistry[Any]:
        return self.registry(PERSIST_DOMAIN)

    @property
    def persistence_handlers(self) -> ComponentRegistry[Any]:
        return self.registry(PERSIST_DOMAIN)


__all__ = ["ComponentStore"]
