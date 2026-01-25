"""orchestrai_django.decorators
=============================

Django-aware public decorators for OrchestrAI.

This module mirrors the core OrchestrAI decorator surface (codec, service, schema,
prompt_section, provider, provider_backend) but derives identities using Django context.

Identity behavior
-----------------
- Identities are 4-part labels (domain.namespace.group.name). Django decorators honor the
  same precedence as core (arg → class attr → decorator defaults → derived fallbacks) while
  relying on Django-aware namespace/token inference.
- The only Django-specific behavior is identity derivation: a small mixin overrides
  ``derive_identity`` to call :class:`~orchestrai_django.identity.resolvers.DjangoIdentityResolver`.
- The mixin is placed first in the MRO to ensure Django identity derivation wins.

This module is intentionally side-effect free (no autodiscovery/autostart).
"""

from orchestrai.decorators.components.codec_decorator import CodecDecorator
from orchestrai.decorators.components.prompt_section_decorator import PromptSectionDecorator
from orchestrai.decorators.components.provider_decorators import (
    ProviderBackendDecorator,
    ProviderDecorator,
)
from orchestrai.decorators.components.schema_decorator import SchemaDecorator
from orchestrai.decorators.components.service_decorator import ServiceDecorator
from orchestrai.identity.domains import DEFAULT_DOMAIN
from orchestrai_django.identity.resolvers import DjangoIdentityResolver

__all__ = [
    "codec",
    "service",
    "schema",
    "prompt_section",
    "provider",
    "provider_backend",
    "persistence_handler",
    "flush_pending_handlers",
    "PersistenceHandlerDecorator",
    "DjangoCodecDecorator",
    "DjangoServiceDecorator",
    "DjangoSchemaDecorator",
    "DjangoPromptSectionDecorator",
    "DjangoProviderDecorator",
    "DjangoProviderBackendDecorator",
]


class DjangoBaseDecoratorMixin:
    """Mixin that overrides identity derivation to use the Django resolver."""

    def derive_identity(
            self,
            cls,  # type: ignore[no-untyped-def]
            *,
            domain: str | None,
            namespace: str | None,
            group: str | None,
            name: str | None,
    ):
        context = {
            "default_domain": getattr(self, "default_domain", DEFAULT_DOMAIN),
            "default_namespace": getattr(self, "default_namespace", None),
            "default_group": getattr(self, "default_group", None),
        }
        return DjangoIdentityResolver().resolve(
            cls,
            domain=domain,
            namespace=namespace,
            group=group,
            name=name,
            context=context,
        )

    # Optional collision policy hook for registries.
    # Keep this here so Django wrappers can expose it uniformly if registries look for it.
    def allow_collision_rewrite(self) -> bool:
        """Hint for registries when collisions are non-strict."""
        from orchestrai_django.settings import STRICT_COLLISIONS

        # If collisions are strict, registries should NOT rewrite.
        return not bool(STRICT_COLLISIONS)


class DjangoCodecDecorator(DjangoBaseDecoratorMixin, CodecDecorator):
    """Django-aware codec decorator (core behavior + Django identity)."""


class DjangoPromptSectionDecorator(DjangoBaseDecoratorMixin, PromptSectionDecorator):
    """Django-aware prompt section decorator (core behavior + Django identity)."""


class DjangoSchemaDecorator(DjangoBaseDecoratorMixin, SchemaDecorator):
    """Django-aware output schema decorator (core behavior + Django identity)."""


class DjangoServiceDecorator(DjangoBaseDecoratorMixin, ServiceDecorator):
    """Django-aware service decorator (core behavior + Django identity)."""


class DjangoProviderDecorator(DjangoBaseDecoratorMixin, ProviderDecorator):
    """Django-aware provider decorator (core behavior + Django identity)."""


class DjangoProviderBackendDecorator(DjangoBaseDecoratorMixin, ProviderBackendDecorator):
    """Django-aware provider backend decorator (core behavior + Django identity)."""


class PersistenceHandlerDecorator:
    """
    Simple decorator for persistence handlers.

    No identity system - just validates and registers by schema class.

    Usage:
        @persistence_handler
        class PatientInitialPersistence(BasePersistenceHandler):
            schema = PatientInitialOutputSchema

            async def persist(self, *, data, context):
                ...
    """

    def __call__(self, cls):
        from orchestrai_django.components.persistence import BasePersistenceHandler

        # Validate handler
        if not issubclass(cls, BasePersistenceHandler):
            raise TypeError(
                f"{cls.__module__}.{cls.__name__} must inherit from BasePersistenceHandler"
            )

        if not callable(getattr(cls, "persist", None)):
            raise TypeError(
                f"{cls.__module__}.{cls.__name__} must implement async persist()"
            )

        schema_cls = getattr(cls, "schema", None)
        if schema_cls is None:
            raise TypeError(
                f"{cls.__module__}.{cls.__name__} must declare 'schema' class attribute"
            )

        # Register with persistence registry
        from orchestrai_django.registry import get_persistence_registry

        registry = get_persistence_registry()
        if registry is not None:
            registry.register(cls)
        else:
            # Queue for later registration
            _pending_handlers.append(cls)

        return cls


# Pending handlers for when registry isn't ready yet
_pending_handlers: list[type] = []


def flush_pending_handlers():
    """Register any pending handlers once registry is available."""
    from orchestrai_django.registry import get_persistence_registry

    registry = get_persistence_registry()
    if registry is None:
        return

    while _pending_handlers:
        handler_cls = _pending_handlers.pop(0)
        registry.register(handler_cls)


codec = DjangoCodecDecorator()
service = DjangoServiceDecorator()
schema = DjangoSchemaDecorator()
prompt_section = DjangoPromptSectionDecorator()
provider = DjangoProviderDecorator()
provider_backend = DjangoProviderBackendDecorator()
persistence_handler = PersistenceHandlerDecorator()
