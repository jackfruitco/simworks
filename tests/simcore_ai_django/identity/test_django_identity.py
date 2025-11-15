# tests/simcore_ai_django/identity/test_django_identity.py
from __future__ import annotations

import types

import pytest

from simcore_ai_django.api import simcore

from simcore_ai_django.decorators.base import DjangoBaseDecorator

# -----------------------------
# Helper: synthesize classes with custom __module__
# -----------------------------
def _new_class(name: str, module: str | None = None, bases: tuple[type, ...] = ()) -> type:
    module = module or "pkg.sub.module"

    def exec_body(ns):
        ns["__module__"] = module

    return types.new_class(name, bases=bases, exec_body=exec_body)


# -----------------------------
# derive_namespace_django precedence (arg > attr > app label/name > module root)
# -----------------------------
@pytest.mark.django_db(transaction=False)
def test_derive_namespace_django_precedence(settings):
    # No matching AppConfig in tests -> falls back to module root
    C1 = _new_class("Foo", module="mychat.app.feature")
    ns = derive_namespace_django(C1, namespace_arg=None, namespace_attr=None)
    assert ns == "mychat"

    # Explicit arg wins
    ns = derive_namespace_django(C1, namespace_arg="explicit_ns", namespace_attr=None)
    assert ns == "explicit_ns"

    # Class attribute second
    class WithNS:
        namespace = "from_attr"

    C2 = _new_class("Foo", bases=(WithNS,))
    ns = derive_namespace_django(C2, namespace_arg=None, namespace_attr=getattr(C2, "namespace", None))
    assert ns == "from_attr"


# -----------------------------
# Global name tokens and strip delegation
# -----------------------------
@pytest.mark.django_db(transaction=False)
def test_get_app_tokens_for_name_and_strip_global_only(settings):
    # Only global tokens defined; ensures helper reads & de-dupes case-insensitively
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = ["Generate", "Service", "service", "RESPONSE"]

    C = _new_class("GeneratePatientInitialResponseService")
    tokens = get_app_tokens_for_name(C)
    # Order preserved on first occurrence; duplicates removed ignoring case
    assert tokens == ("Generate", "Service", "RESPONSE")

    # Delegation to core strip (edges only, case-insensitive)
    stripped = strip_name_tokens_django("GeneratePatientInitialResponseService", tokens)
    assert stripped == "PatientInitialResponse"


# -----------------------------
# DjangoBaseDecorator end-to-end identity derivation (no registry)
# -----------------------------
class _NoRegistryDecorator(DjangoBaseDecorator):
    default_kind = "service"

    def get_registry(self):
        return None


@pytest.mark.django_db(transaction=False)
def test_django_base_decorator_derives_identity_with_tokens(settings):
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = ["Generate", "Service"]

    @_NoRegistryDecorator()
    class GeneratePatientInitialResponseService:
        __module__ = "telemed.sim.feature"
        pass

    cls = GeneratePatientInitialResponseService
    assert hasattr(cls, "identity") and hasattr(cls, "identity_obj")
    ns, kd, nm = cls.identity

    # namespace from module root (no AppConfig in tests)
    assert ns == "telemed"
    # domain default from decorator subclass
    assert kd == "service"
    # Steps: derive_name (lower class) -> strip edges -> normalize (already lower)
    # Result is compact lower string (no camel case left to split)
    assert nm == "patientinitialresponse"


# -----------------------------
# Django codec decorator registers with registry
# -----------------------------
@pytest.mark.django_db(transaction=False)
def test_django_codec_decorator_registers_and_duplicate_skips(settings):
    settings.SIMCORE_COLLISIONS_STRICT = True
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = ["Generate", "Codec"]

    @django_codec
    class GenerateSomethingCodec:
        __module__ = "telemed.training"
        pass

    # Registered once
    ident = GenerateSomethingCodec.identity
    cls_resolved = codec_registry.resolve(ident)
    assert cls_resolved is GenerateSomethingCodec

    # Duplicate register (same class + same identity) should be idempotent
    codec_registry.maybe_register(ident, GenerateSomethingCodec)
    assert codec_registry.resolve(ident) is GenerateSomethingCodec


@pytest.mark.django_db(transaction=False)
def test_django_codec_decorator_collision_strict_and_nonstrict(settings):
    # Strict mode: collision raises
    settings.SIMCORE_COLLISIONS_STRICT = True
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = []

    @django_codec
    class UniqueThing:
        __module__ = "ns.collide"
        name = "same_name"  # explicit to force collision later
        pass

    ident = UniqueThing.identity

    with pytest.raises(IdentityCollisionError):
        # Different class with the same identity
        class DifferentThing:  # not decorated; registry invoked directly
            pass

        codec_registry.maybe_register(ident, DifferentThing)

    # Non-strict mode: warn/record but do not raise
    settings.SIMCORE_COLLISIONS_STRICT = False

    class AnotherDifferentThing:
        pass

    # should not raise now
    codec_registry.maybe_register(ident, AnotherDifferentThing)
    # Registry notes the collision internally
    collisions = list(codec_registry.collisions())
    assert ident in collisions
