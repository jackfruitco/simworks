# simcore_ai/services/decorators.py
"""Core (non-Django) LLM service decorator built on the class-based base decorator.

This module defines the **core** `llm_service` decorator using the shared,
framework-agnostic `BaseRegistrationDecorator`. It supports decorating both
**classes** and **async functions** (functions are wrapped into a service class).

Identity resolution (core defaults) is module-centric and implemented in the
base class:
- origin: first module segment or "simcore"
- bucket: second module segment or "default"
- name:   snake_case(object name with common affixes removed)

Domain-specific behavior here:
- Function targets are wrapped into a `BaseLLMService` subclass with a sensible
  `on_success` adapter that calls the original function with `(simulation, slim)`
  or just `(simulation)` depending on arity.
- Service extras:
    * `codec` -> `codec_name` (default "default")
    * `prompt_plan` -> tuple-ized as `prompt_plan`
- Registration:
    * Uses `ServiceRegistry.register(service_cls, debug=None)`
    * Enforces tuple³ uniqueness by handling `DuplicateServiceIdentityError`
      and appending a hyphen-int suffix to the **name**: `name-2`, `name-3`, ...
      WARNING is logged for each collision; import never crashes.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Type
from collections.abc import Callable

from simcore_ai.decorators.registration import BaseRegistrationDecorator
from simcore_ai.services import BaseLLMService  # runtime dependency for function wrapping

# Registries are intentionally core-only here (no Django imports)
try:
    from simcore_ai.services.registry import ServiceRegistry  # singular per finalized plan
except Exception:  # pragma: no cover - keep imports resilient at import time
    ServiceRegistry = None  # type: ignore[assignment]

# Domain-specific duplicate error type (raised atomically by the registry)
try:
    from simcore_ai.services.registry import DuplicateServiceIdentityError  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    class DuplicateServiceIdentityError(Exception):  # fallback to ensure collision loop works
        pass

log = logging.getLogger(__name__)


class ServiceRegistrationMixin:
    """Domain mixin for Services: function wrapping, extras binding, and registration."""

    # ----- function → class wrapping -----
    def wrap_function(self, func: Callable[..., Any]) -> Type[Any]:
        """Wrap an async function into a `BaseLLMService` subclass.

        The generated service class adapts `on_success` to the function signature:
        - (simulation, slim) -> forwarded
        - (simulation)       -> forwarded
        - otherwise          -> returns None
        """
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                "llm_service expects an async function when decorating callables; "
                f"got {func!r}"
            )

        class _FnService(BaseLLMService):  # type: ignore[misc]
            async def on_success(self, simulation, slim):
                sig = inspect.signature(func)
                params = list(sig.parameters.values())
                if len(params) >= 2:
                    return await func(simulation, slim)
                if len(params) == 1:
                    return await func(simulation)
                return None

        # Provide stable introspection metadata
        _FnService.__name__ = f"{func.__name__}_Service"
        _FnService.__module__ = getattr(func, "__module__", __name__)

        return _FnService

    # ----- extras binding (domain-specific knobs) -----
    def bind_extras(self, obj: Any, extras: dict[str, Any]) -> None:
        """Bind optional decorator extras to the class (no-op if absent)."""
        try:
            codec = extras.get("codec", None)
            if codec is not None:
                setattr(obj, "codec_name", codec)
            elif not hasattr(obj, "codec_name"):
                setattr(obj, "codec_name", "default")

            prompt_plan = extras.get("prompt_plan", None)
            if prompt_plan is not None:
                try:
                    setattr(obj, "prompt_plan", tuple(prompt_plan))
                except Exception:
                    setattr(obj, "prompt_plan", ())
            elif not hasattr(obj, "prompt_plan"):
                setattr(obj, "prompt_plan", ())
        except Exception:  # pragma: no cover - extras must never break import
            log.debug("llm_service.bind_extras: suppressed extras binding error", exc_info=True)

    # ----- registration with collision handling -----
    def register(self, obj: Any) -> None:
        """Register the service class with tuple³ uniqueness and collision resolution."""
        if ServiceRegistry is None:  # registry unavailable at import time; skip safely
            log.debug("ServiceRegistry unavailable; skipping registration for %s", getattr(obj, "__name__", obj))
            return

        # Expect identity to be present already (set by BaseRegistrationDecorator)
        base_origin = getattr(obj, "origin", None)
        base_bucket = getattr(obj, "bucket", None)
        base_name = getattr(obj, "name", None)

        if not (base_origin and base_bucket and base_name):
            log.debug(
                "Service identity incomplete; skipping registration: origin=%r bucket=%r name=%r",
                base_origin, base_bucket, base_name
            )
            return

        suffix = 1
        while True:
            try:
                # Attempt registry insertion (should be atomic & raise on dup)
                ServiceRegistry.register(obj, debug=None)  # type: ignore[attr-defined]
                return
            except DuplicateServiceIdentityError:
                suffix += 1
                new_name = f"{base_name}-{suffix}"
                setattr(obj, "name", new_name)
                log.warning(
                    "Collision for service identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    base_origin, base_bucket, base_name,
                    base_origin, base_bucket, new_name,
                )
                # Loop continues with updated name


class ServiceRegistrationDecorator(BaseRegistrationDecorator, ServiceRegistrationMixin):
    """Core Services decorator: supports classes and async functions."""


# Ready-to-use instance (core)
llm_service = ServiceRegistrationDecorator()

__all__ = ["llm_service", "ServiceRegistrationDecorator", "ServiceRegistrationMixin"]
