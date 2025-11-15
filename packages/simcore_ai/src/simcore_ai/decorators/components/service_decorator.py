# simcore_ai/decorators/components/service_decorator.py


from simcore_ai.registry import BaseRegistry

"""
Core service decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "service" if not provided).
- Registers the class in the global `services` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

from typing import Any, Type, TypeVar
import logging

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.components.services.base import BaseService
from simcore_ai.registry.singletons import services as _Registry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class ServiceDecorator(BaseDecorator):
    """
    Service decorator specialized for BaseService subclasses.

    Usage
    -----
        from simcore_ai.decorators import service

        @service
        class MyService(BaseService):
            ...

        # or with explicit hints
        @service(namespace="simcore", name="json")
        class MyService(BaseService):
            ...
    """

    def get_registry(self) -> BaseRegistry:
        # Always register into the service registry
        return _Registry

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register service classes
        if not issubclass(candidate, BaseService):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseService to use @service"
            )
        super().register(candidate)
