"""orchestrai_django.decorators
=============================

Django-aware public decorators for OrchestrAI.

This module mirrors the core OrchestrAI decorator surface (codec, service, schema,
prompt_section) but derives identities using Django context.

Implementation notes
--------------------
- We reuse the core *domain* decorators (CodecDecorator, ServiceDecorator, SchemaDecorator,
  PromptSectionDecorator) so we keep the same registry selection, type guards, and logging.
- The only Django-specific behavior is identity derivation: a small mixin overrides
  ``derive_identity`` to call :class:`~orchestrai_django.identity.resolvers.DjangoIdentityResolver`.
- The mixin is placed first in the MRO to ensure Django identity derivation wins.

This module is intentionally side-effect free (no autodiscovery/autostart).
"""

from orchestrai.decorators import provider, provider_backend
from orchestrai.decorators.components.codec_decorator import CodecDecorator
from orchestrai.decorators.components.prompt_section_decorator import PromptSectionDecorator
from orchestrai.decorators.components.schema_decorator import SchemaDecorator
from orchestrai.decorators.components.service_decorator import ServiceDecorator
from orchestrai_django.identity.resolvers import DjangoIdentityResolver

__all__ = [
    "codec",
    "service",
    "schema",
    "prompt_section",
    "provider",
    "provider_backend",
]


class DjangoBaseDecoratorMixin:
    """Mixin that overrides identity derivation to use the Django resolver."""

    def derive_identity(
            self,
            cls,  # type: ignore[no-untyped-def]
            *,
            namespace: str | None,
            kind: str | None,
            name: str | None,
    ):
        return DjangoIdentityResolver().resolve(
            cls,
            namespace=namespace,
            kind=kind,
            name=name,
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


codec = DjangoCodecDecorator()
service = DjangoServiceDecorator()
schema = DjangoSchemaDecorator()
prompt_section = DjangoPromptSectionDecorator()
