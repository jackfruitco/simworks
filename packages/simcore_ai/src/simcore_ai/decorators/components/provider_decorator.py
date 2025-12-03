# simcore_ai/decorators/components/provider_decorator.py
"""
Core provider decorator.

- Derives & pins identity via IdentityResolver (kind/namespace/name via resolver + hints).
- Registers provider classes in the global `providers` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
- Enforces that only BaseCodec subclasses can be decorated.
"""
import logging
from typing import Any, Type, TypeVar

from simcore_ai.components.providerkit import BaseProvider
from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.registry import BaseRegistry
from simcore_ai.registry.singletons import providers as provider_registry

__all__ = ("ProviderDecorator", "provider")

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class ProviderDecorator(BaseDecorator):
    """
    Provider decorator specialized for BaseProvider subclasses.

    Usage
    -----
        from simcore_ai.decorators.provider import provider

        @provider
        class MyProvider(BaseProvider):
            ...

        # or with explicit hints
        @provider(namespace="openai", kind="responses", name="prod")
        class OpenAiProd(BaseProvider):
            ...
    """

    def get_registry(self) -> BaseRegistry:
        """Return the global providers registry singleton."""
        return provider_registry

    def register(self, candidate: Type[Any]) -> None:
        """Register a provider class after guarding its base type.

        Ensures only BaseProvider subclasses are registered into the providers registry.
        """
        if not issubclass(candidate, BaseProvider):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseProvider to use @provider"
            )
        super().register(candidate)


# Public instance used as the decorator in app code
provider = ProviderDecorator()
