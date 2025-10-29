# tests/simcore_ai_django/identity/test_django_identity_appconfig.py
from __future__ import annotations

import types
import pytest

from simcore_ai_django.decorators.helpers import (
    derive_namespace_django,
    get_app_tokens_for_name,
    strip_name_tokens_django,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator


def _new_class(name: str, module: str, bases: tuple[type, ...] = ()) -> type:
    def exec_body(ns):
        ns["__module__"] = module
    return types.new_class(name, bases=bases, exec_body=exec_body)


@pytest.mark.django_db(transaction=False)
def test_namespace_prefers_app_label_over_module_root(settings):
    # class lives under the dummy app's module path -> app label should be used
    C = _new_class(
        "AnyName",
        module="tests.simcore_ai_django.fixtures.dummyapp.feature.submod",
    )
    ns = derive_namespace_django(C, namespace_arg=None, namespace_attr=None)
    assert ns == "dummyapp"  # AppConfig.label takes precedence over module root


@pytest.mark.django_db(transaction=False)
def test_app_tokens_merge_with_globals_no_dupes_case_insensitive(settings):
    # DummyApp tokens: ("Generate", "Response", "Service")
    # Globals include overlap and extras; duplicates (case-insensitive) are dropped,
    # order preserves first occurrence across app tokens then globals
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = ["generate", "Codec", "SERVICE", "Extra"]

    C = _new_class("Foo", module="tests.simcore_ai_django.fixtures.dummyapp.feature")
    tokens = get_app_tokens_for_name(C)
    assert tokens == ("Generate", "Response", "Service", "Codec", "Extra")

    # Verify stripping with merged tokens handles edges only, case-insensitive
    stripped = strip_name_tokens_django("GeneratePatientResponseService", tokens)
    assert stripped == "Patient"


class _NoRegistryDecorator(DjangoBaseDecorator):
    default_kind = "service"
    def get_registry(self):
        return None


@pytest.mark.django_db(transaction=False)
def test_django_base_decorator_uses_app_label_and_app_tokens(settings):
    # No globals; rely on AppConfig.IDENTITY_STRIP_TOKENS
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = []

    @_NoRegistryDecorator()
    class GeneratePatientResponseService:
        __module__ = "tests.simcore_ai_django.fixtures.dummyapp.feature"
        pass

    ns, kd, nm = GeneratePatientResponseService.identity
    assert ns == "dummyapp"  # from AppConfig.label
    assert kd == "service"   # default_kind from decorator subclass
    # derive_name -> "generatepatientresponseservice" (lower), then app tokens strip edges -> "Patient"
    # normalize_name then snake-cases if needed; since "Patient" is simple, lowercased becomes:
    assert nm == "patient"