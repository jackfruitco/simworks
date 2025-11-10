# tests/simcore_ai_django/services/test_service_registry.py
from __future__ import annotations

import types
import pytest

from simcore_ai_django.components.services.registry import (
    services as service_registry,
    IdentityCollisionError,
    IdentityValidationError,
)


def _new_class(name: str, module: str | None = None, bases: tuple[type, ...] = ()) -> type:
    module = module or "pkg.sub.module"
    def exec_body(ns):
        ns["__module__"] = module
    return types.new_class(name, bases=bases, exec_body=exec_body)


@pytest.mark.django_db(transaction=False)
def test_register_and_resolve_success(settings):
    settings.SIMCORE_COLLISIONS_STRICT = True

    C = _new_class("FooService", module="telemed.ops")
    ident = ("telemed", "service", "foo_service")

    # Fresh register
    service_registry.maybe_register(ident, C)

    # Resolution returns same class
    resolved = service_registry.resolve(ident)
    assert resolved is C

    # Listing contains our registration
    items = list(service_registry.list())
    assert any(item.identity == ident and item.cls is C for item in items)


@pytest.mark.django_db(transaction=False)
def test_duplicate_same_class_same_identity_is_idempotent(settings):
    settings.SIMCORE_COLLISIONS_STRICT = True

    C = _new_class("BarService", module="alpha.beta")
    ident = ("alpha", "service", "bar_service")

    service_registry.maybe_register(ident, C)
    # duplicate register should be silently idempotent
    service_registry.maybe_register(ident, C)

    assert service_registry.resolve(ident) is C
    # collisions list should remain empty
    assert list(service_registry.collisions()) == []


@pytest.mark.django_db(transaction=False)
def test_collision_handling_strict_and_non_strict(settings):
    ident = ("ns", "service", "same")

    settings.SIMCORE_COLLISIONS_STRICT = True
    C1 = _new_class("S1", module="ns.mod")
    C2 = _new_class("S2", module="ns.mod2")

    # First registration ok
    service_registry.maybe_register(ident, C1)

    # Strict mode: second different class with same identity -> raises
    with pytest.raises(IdentityCollisionError):
        service_registry.maybe_register(ident, C2)

    # Non-strict mode: warn/record but no raise
    settings.SIMCORE_COLLISIONS_STRICT = False
    C3 = _new_class("S3", module="ns.mod3")
    service_registry.maybe_register(ident, C3)
    assert ident in set(service_registry.collisions())


@pytest.mark.django_db(transaction=False)
@pytest.mark.parametrize(
    "bad",
    [
        ("", "service", "x"),
        ("ns", "", "x"),
        ("ns", "service", ""),
        (None, "service", "x"),          # type: ignore[arg-type]
        ("ns", None, "x"),               # type: ignore[arg-type]
        ("ns", "service", None),         # type: ignore[arg-type]
        ("ns", "service"),               # type: ignore[misc]
        ("ns", "service", "x", "extra"), # type: ignore[misc]
    ],
)
def test_identity_validation_errors(settings, bad):
    C = _new_class("Bad", module="ns.m")
    with pytest.raises(IdentityValidationError):
        # any malformed identity should raise before mutating registry
        service_registry.maybe_register(bad, C)  # type: ignore[arg-type]