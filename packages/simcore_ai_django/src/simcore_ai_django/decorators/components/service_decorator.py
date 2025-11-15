# simcore_ai_django/decorators/components/service_decorator.py
"""
Core service decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "codec" if not provided).
- Registers the class in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""


import logging
from typing import Any, Type, TypeVar

from simcore_ai.components.services.base import BaseService
from simcore_ai.registry import BaseRegistry
from simcore_ai.registry.singletons import services as _Registry
from simcore_ai_django.decorators.base import DjangoBaseDecorator

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class DjangoServiceDecorator(DjangoBaseDecorator):
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

        # or, namespaced:
        from simcore_ai.api import decorators as simcore

        @simcore.service(namespace="simcore", name="json")
        class MyService(BaseService):
            ...
    """

    def get_registry(self) -> BaseRegistry:
        # Always register into the service registry
        return _Registry

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register Service classes
        if not issubclass(candidate, BaseService):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseService to use @service"
            )
        super().register(candidate)
        self._attach_task(candidate)

    @staticmethod
    def _attach_task(candidate: Type[Any]) -> None:
        """Attach a Django Task to the given service class, if appropriate."""
        # Attach Django Task for each concrete service if not already present
        if getattr(candidate, "abstract", False):
            return
        if getattr(candidate, "task", None) is not None:
            return
        try:
            from django.tasks import task as django_task
        except Exception:
            logger.exception("Failed to import django.tasks; skipping task registration for %s", candidate)
            return
        identity = getattr(candidate, "identity", None)
        if identity is not None and hasattr(identity, "as_str"):
            task_name = f"simcore.{identity.as_str}"
        else:
            task_name = f"{candidate.__module__}.{candidate.__name__}"

        async def _runner(**ctx):
            overrides = ctx.pop("service_overrides", {})
            svc = candidate.using(**overrides)
            return await svc.arun(**ctx)

        django_task_obj = django_task(name=task_name)(_runner)
        setattr(candidate, "task", django_task_obj)
        logger.info("Attached Django Task %s to service %s", task_name, candidate)
