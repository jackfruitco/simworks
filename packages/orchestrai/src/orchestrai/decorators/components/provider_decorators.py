# orchestrai/decorators/components/provider_decorator.py
"""
Core provider decorators.

This module defines two decorators: one for Provider Backends, and one for Provider instances.

- Derive & pin identity via IdentityResolver (domain/namespace/group/name via resolver + hints).
- Register provider backend classes in the global `provider_backends` registry.
- Register provider “wiring” classes in the global `providers` registry.
- Preserve the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
- Enforce that only BaseProvider subclasses can be decorated.
"""
import logging
from typing import Any, Optional, Type

from orchestrai.components.providerkit import BaseProvider
from orchestrai.decorators.base import BaseDecorator
from orchestrai.identity.domains import (
    PROVIDER_BACKENDS_DOMAIN,
    PROVIDERS_DOMAIN,
)
from orchestrai.registry import ComponentRegistry
from orchestrai.registry import (
    provider_backends as provider_backend_registry,
    providers as providers_registry,
)

logger = logging.getLogger(__name__)

__all__ = ("ProviderBackendDecorator", "ProviderDecorator")


class ProviderBackendDecorator(BaseDecorator):
    """
    Provider decorator specialized for BaseProvider subclasses.

    Usage
    -----
        from orchestrai.decorators.backend import backend

        @backend
        class MyProvider(BaseProvider):
            ...

        # or with explicit hints (for a backend, name should be "backend")
        @backend(namespace="openai", group="responses", name="backend")
        class OpenAiResponsesBackend(BaseProvider):
            ...
    """

    default_domain = PROVIDER_BACKENDS_DOMAIN

    def get_registry(self) -> ComponentRegistry:
        """Return the global provider backends registry singleton (identity-keyed)."""
        return provider_backend_registry

    # Human-friendly log label
    log_category = "provider_backends"

    def derive_identity(
            self,
            cls: Type[Any],
            *,
            domain: Optional[str],
            namespace: Optional[str],
            group: Optional[str],
            name: Optional[str],
    ):
        domain_override = domain or self.default_domain
        return super().derive_identity(
            cls,
            domain=domain_override,
            namespace=namespace,
            group=group,
            name=name,
        )

    def register(self, candidate: Type[Any]) -> None:
        """Register a backend class after guarding its base type.

        Ensures only BaseProvider subclasses are registered into the provider backends registry.
        """
        if not issubclass(candidate, BaseProvider):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseProvider to use @provider_backend"
            )
        candidate.DOMAIN = PROVIDER_BACKENDS_DOMAIN
        try:
            candidate.domain = PROVIDER_BACKENDS_DOMAIN
        except Exception:
            pass
        super().register(candidate)


class ProviderDecorator(BaseDecorator):
    """
    Provider decorator specialized for BaseProvider subclasses.

    Usage
    -----
        from orchestrai.decorators.provider import provider

        @provider
        class MyProvider(BaseProvider):
            ...

        # or with explicit hints (name corresponds to the provider profile, e.g. "default" or "prod")
        @provider(namespace="openai", group="responses", name="prod")
        class OpenAiResponsesProvider(BaseProvider):
            ...
    """

    default_domain = PROVIDERS_DOMAIN

    def get_registry(self) -> ComponentRegistry:
        """Return the global providers registry singleton (identity-keyed)."""
        return providers_registry

    # Human-friendly log label
    log_category = "providers"

    def register(self, candidate: Type[Any]) -> None:
        """Register a provider class after guarding its base type.

        Ensures only BaseProvider subclasses are registered into the providers registry.
        """
        if not issubclass(candidate, BaseProvider):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseProvider to use @provider"
            )
        super().register(candidate)
