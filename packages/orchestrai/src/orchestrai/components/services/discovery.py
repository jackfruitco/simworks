from __future__ import annotations

import importlib
from typing import Iterable

from orchestrai.components.services.exceptions import ServiceDiscoveryError
from orchestrai.registry.services import ensure_service_registry


def discover_services(modules: Iterable[str]) -> list[str]:
    """Import discovery modules and ensure the service registry exists."""

    discovered: list[str] = []
    for module in modules:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            # Only re-raise when the target module itself is missing (not a child import).
            if exc.name == module.split(".")[0]:
                raise ServiceDiscoveryError(f"Service discovery module '{module}' not found") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise ServiceDiscoveryError(f"Failed to import service discovery module '{module}'") from exc
        else:
            discovered.append(module)

    # Ensure the registry is hydrated even if no modules were discovered.
    try:
        ensure_service_registry()
    except LookupError:
        # No active app; allow discovery to proceed without a registry.
        pass

    return discovered


def list_services(*, as_str: bool = False):
    """Return all registered services using the active registry."""

    registry = ensure_service_registry()
    return registry.items(as_str=as_str)


__all__ = ["discover_services", "list_services"]
