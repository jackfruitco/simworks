# orchestrai/decorators/components/service_decorator.py
"""
Core service decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "service" if not provided).
- Registers the class in the global `services` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

import logging
from typing import Any, Type

from orchestrai.components.services.service import BaseService
from orchestrai.decorators.base import BaseDecorator
from orchestrai.registry import ComponentRegistry
from orchestrai.registry import services as services_registry

logger = logging.getLogger(__name__)

__all__ = ("ServiceDecorator",)


class ServiceDecorator(BaseDecorator):
    """
    Service decorator specialized for BaseService subclasses.

    Usage
    -----
        from orchestrai.decorators import service

        @service
        class MyService(BaseService):
            ...

        # or with explicit hints
        @service(namespace="orchestrai", name="json")
        class MyService(BaseService):
            ...
    """

    def get_registry(self) -> ComponentRegistry:
        # Always register into the service registry
        return services_registry

    # Human-friendly log label
    log_category = "services"

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register service classes
        if not issubclass(candidate, BaseService):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseService to use @service"
            )
        super().register(candidate)
