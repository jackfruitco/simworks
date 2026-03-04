"""Compatibility re-export for the service registry.

Service registry helpers now live under :mod:`orchestrai.registry.services`.
"""

from orchestrai.registry.services import ServiceRegistry, ensure_service_registry, service_registry


def get_component_store(app=None):  # pragma: no cover - compatibility helper
    from orchestrai.registry.active_app import get_component_store as _get

    return _get(app)


__all__ = [
    "ServiceRegistry",
    "ensure_service_registry",
    "get_component_store",
    "service_registry",
]
