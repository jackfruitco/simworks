from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.base import BaseRegistry
from orchestrai.utils.proxy import Proxy

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from orchestrai.components.services.service import BaseService
else:  # pragma: no cover - runtime fallback to break cycles
    BaseService = object  # type: ignore


class ServiceRegistry(BaseRegistry[Identity, "BaseService"]):
    """Registry specialized for service classes keyed by identity."""

    domain: str = SERVICES_DOMAIN

    def __init__(self) -> None:
        super().__init__(coerce_key=lambda svc: Identity.get_for(getattr(svc, "identity", svc)).label)


def _service_registry_proxy():
    from orchestrai.registry.active_app import get_component_store

    store = get_component_store()
    if store is None:
        return None
    return store.registry(SERVICES_DOMAIN)


service_registry = Proxy(_service_registry_proxy)


def get_component_store(app: Any | None = None):  # pragma: no cover - compatibility helper
    from orchestrai.registry.active_app import get_component_store as _get

    return _get(app)


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
