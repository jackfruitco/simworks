# orchestrai_django/decorators/components/service_decorator.py
"""
Core service decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "codec" if not provided).
- Registers the class in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""


import logging
from typing import Any, Type, TypeVar

from orchestrai.components.services.service import BaseService
from orchestrai.registry import ComponentRegistry
from orchestrai.registry.singletons import services as _Registry
from orchestrai_django.decorators.base import DjangoBaseDecorator


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class DjangoServiceDecorator(DjangoBaseDecorator):
    """
    Service decorator specialized for BaseService subclasses.

    Usage
    -----
        from orchestrai.decorators import service

        @service
        class MyService(BaseService):
            ...

        # or with explicit hints
        @service(namespace="simcore", name="json")
        class MyService(BaseService):
            ...

        # or, namespaced:
        from orchestrai.api import decorators as simcore

        @simcore.service(namespace="simcore", name="json")
        class MyService(BaseService):
            ...
    """

    def get_registry(self) -> ComponentRegistry:
        # Always register into the service registry
        return _Registry

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register Service classes
        if not issubclass(candidate, BaseService):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseService to use @service"
            )
        super().register(candidate)
