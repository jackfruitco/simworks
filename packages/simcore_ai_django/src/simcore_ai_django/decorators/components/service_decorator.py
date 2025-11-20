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

# Add Django task import at the module level
from django.tasks import task as django_task

# --- Shared module-level task entrypoint and adapter for Django tasks ---
from functools import wraps

@django_task
async def _run_service_task(identity_str: str, ctx: dict | None = None, overrides: dict | None = None):
    """
    Generic Django Task entrypoint for all simcore services.

    Django's task backend requires the task function to be defined at module
    level. We use this single entrypoint and let per-service adapters pass
    the Identity string and execution context.
    """
    from simcore_ai.registry.singletons import services as services_registry

    ctx = ctx or {}
    overrides = overrides or {}

    svc_cls = await services_registry.aget(identity_str)

    # Merge any existing context in overrides with ctx, with ctx taking precedence.
    base_context = dict(overrides.pop("context", {}))
    base_context.update(ctx)

    # Pass the full context into the service so required_context_keys are satisfied.
    svc = svc_cls.using(context=base_context, **overrides)

    # Fire-and-forget: rely on side effects (DB writes, websockets, etc.).
    # Do NOT return the LLMResponse object, since Django's task backend
    # expects JSON-serializable return values.
    await svc.arun()
    return None


class ServiceTaskAdapter:
    """
    Thin adapter that exposes a per-service `.task` interface while delegating
    to the shared module-level `_run_service_task` Task.

    This satisfies Django's requirement that the underlying Task function is
    module-level, while still letting callers do:

        GenerateInitialResponse.task.enqueue(**ctx)
    """

    def __init__(self, base_task, identity_str: str):
        self._base_task = base_task
        self._identity_str = identity_str

    def enqueue(self, *, ctx: dict | None = None, overrides: dict | None = None):
        """Enqueue this service via the shared module-level task.

        `ctx` is treated as the service context (e.g. must contain
        required_context_keys like `simulation_id`). Optional `overrides`
        are forwarded to the service constructor.
        """
        ctx = ctx or {}
        overrides = overrides or {}
        return self._base_task.enqueue(identity_str=self._identity_str, ctx=ctx, overrides=overrides)

    async def aenqueue(self, *, ctx: dict | None = None, overrides: dict | None = None):
        """Async enqueue variant for use from async contexts."""
        ctx = ctx or {}
        overrides = overrides or {}
        return await self._base_task.aenqueue(identity_str=self._identity_str, ctx=ctx, overrides=overrides)

    def using(self, *args, **kwargs):
        """
        Forward `.using()` to the underlying Task and wrap the result in a new adapter.
        """
        new_task = self._base_task.using(*args, **kwargs)
        return ServiceTaskAdapter(new_task, self._identity_str)

    def __getattr__(self, item):
        # Delegate any other attributes (e.g. backend, priority) to the base Task.
        return getattr(self._base_task, item)

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
        # Treat a class as abstract only if it defines `abstract` on itself, not just via inheritance.
        is_abstract = getattr(candidate, "abstract", False) and "abstract" in candidate.__dict__
        if is_abstract:
            return
        if getattr(candidate, "task", None) is not None:
            return
        identity = getattr(candidate, "identity", None)
        if identity is not None and hasattr(identity, "as_str"):
            task_name = f"simcore.{identity.as_str}"
        else:
            task_name = f"{candidate.__module__}.{candidate.__name__}"

        # Attach a per-service adapter around the shared module-level task.
        if identity is not None and hasattr(identity, "as_str"):
            identity_str = identity.as_str
        else:
            # Fallback: use module + class name as a pseudo-identity.
            identity_str = task_name

        candidate_task = ServiceTaskAdapter(_run_service_task, identity_str)
        setattr(candidate, "task", candidate_task)
        logger.info("Attached Django Task adapter %s to service %s", task_name, candidate)
