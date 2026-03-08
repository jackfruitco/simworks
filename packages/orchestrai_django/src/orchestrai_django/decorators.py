"""Django-aware public decorators for OrchestrAI."""

from __future__ import annotations

from orchestrai.decorators.components.instruction_decorator import InstructionDecorator
from orchestrai.decorators.components.service_decorator import ServiceDecorator
from orchestrai.identity.domains import DEFAULT_DOMAIN, INSTRUCTIONS_DOMAIN, SERVICES_DOMAIN
from orchestrai_django.identity.resolvers import DjangoIdentityResolver

__all__ = [
    "DjangoInstructionDecorator",
    "DjangoServiceDecorator",
    "instruction",
    "orca",
    "service",
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

    def allow_collision_rewrite(self) -> bool:
        """Hint for registries when collisions are non-strict."""
        from orchestrai_django.settings import STRICT_COLLISIONS

        return not bool(STRICT_COLLISIONS)


class DjangoServiceDecorator(DjangoBaseDecoratorMixin, ServiceDecorator):
    """Django-aware service decorator (core behavior + Django identity)."""

    def derive_identity(
        self,
        cls,  # type: ignore[no-untyped-def]
        *,
        domain: str | None,
        namespace: str | None,
        group: str | None,
        name: str | None,
    ):
        return DjangoBaseDecoratorMixin.derive_identity(
            self,
            cls,
            domain=domain or SERVICES_DOMAIN,
            namespace=namespace,
            group=group,
            name=name,
        )


class DjangoInstructionDecorator(DjangoBaseDecoratorMixin, InstructionDecorator):
    """Django-aware instruction decorator (core behavior + Django identity)."""

    def derive_identity(
        self,
        cls,  # type: ignore[no-untyped-def]
        *,
        domain: str | None,
        namespace: str | None,
        group: str | None,
        name: str | None,
    ):
        return DjangoBaseDecoratorMixin.derive_identity(
            self,
            cls,
            domain=domain or INSTRUCTIONS_DOMAIN,
            namespace=namespace,
            group=group,
            name=name,
        )


class _OrcaDecorators:
    @property
    def service(self):
        return service

    @property
    def instruction(self):
        return instruction


instruction = DjangoInstructionDecorator()
service = DjangoServiceDecorator()
orca = _OrcaDecorators()
