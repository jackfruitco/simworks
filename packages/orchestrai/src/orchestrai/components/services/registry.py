from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry import ComponentRegistry, get_component_store, registry_proxy

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from orchestrai.components.services.service import BaseService
else:  # pragma: no cover - runtime fallback to break cycles
    BaseService = object  # type: ignore


class ServiceRegistry(ComponentRegistry["BaseService"]):
    """Registry specialized for service classes."""

    domain: str = SERVICES_DOMAIN


service_registry = registry_proxy(SERVICES_DOMAIN)


def ensure_service_registry(app: Any | None = None) -> ServiceRegistry:
    """Return the active ServiceRegistry, upgrading the store if necessary."""

    store = get_component_store(app)
    if store is None:
        raise LookupError("No active component store is available")

    registry = store.registry(SERVICES_DOMAIN)
    if isinstance(registry, ServiceRegistry):
        return registry

    upgraded = ServiceRegistry()
    for cls in registry.items():
        upgraded.register(cls, strict=True)
    store._registries[SERVICES_DOMAIN] = upgraded  # type: ignore[attr-defined]
    return upgraded


__all__ = ["ServiceRegistry", "service_registry", "ensure_service_registry"]
