# tests/simcore_ai_django/services/test_service_decorator.py
from __future__ import annotations

import pytest

from simcore_ai_django.services.registry import (
    services as service_registry,
    IdentityCollisionError,
)
from simcore_ai_django.services.decorators import llm_service


@pytest.mark.django_db(transaction=False)
def test_llm_service_decorator_derives_and_registers(settings):
    # global name-only tokens (case-insensitive, edges-only)
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = ["Generate", "Service"]
    settings.SIMCORE_COLLISIONS_STRICT = True

    @llm_service
    class GeneratePatientService:
        __module__ = "telemed.chat.entry"

    # Identity should be attached and registered
    ns, kd, nm = GeneratePatientService.identity
    assert ns == "telemed"   # module root fallback (no AppConfig fixture here)
    assert kd == "service"   # domain default for service decorator
    # derive_name (lower class) -> strip edges -> normalize (already lower)
    assert nm == "patient"

    # Registry should resolve to the decorated class
    resolved = service_registry.resolve(GeneratePatientService.identity)
    assert resolved is GeneratePatientService


@pytest.mark.django_db(transaction=False)
def test_llm_service_decorator_duplicate_is_idempotent(settings):
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = []
    settings.SIMCORE_COLLISIONS_STRICT = True

    @llm_service
    class EchoService:
        __module__ = "ns.echo"

    ident = EchoService.identity
    # second registration with same class + identity is a no-op
    service_registry.maybe_register(ident, EchoService)
    assert service_registry.resolve(ident) is EchoService


@pytest.mark.django_db(transaction=False)
def test_llm_service_decorator_collision_strict_vs_non_strict(settings):
    # Strict: different class, same identity -> error
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = []
    settings.SIMCORE_COLLISIONS_STRICT = True

    @llm_service
    class UniqueService:
        __module__ = "acme.x"
        name = "fixed_name"   # explicit forces stable identity to collide later

    ident = UniqueService.identity

    class OtherService:
        pass

    with pytest.raises(IdentityCollisionError):
        service_registry.maybe_register(ident, OtherService)

    # Non-strict: warn/record but do not raise
    settings.SIMCORE_COLLISIONS_STRICT = False

    class ThirdService:
        pass

    service_registry.maybe_register(ident, ThirdService)
    assert ident in set(service_registry.collisions())