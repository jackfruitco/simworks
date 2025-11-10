from __future__ import annotations

import pytest

from simcore_ai_django.components.services.decorators import ai_service
from simcore_ai_django.components.services.registry import services as service_registry


@pytest.mark.django_db(transaction=False)
def test_llm_service_uses_app_label_and_app_tokens(settings):
    # ensure globals don't interfere; rely solely on AppConfig tokens
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = []

    @ai_service
    class GeneratePatientService:
        __module__ = "tests.simcore_ai_django.fixtures.dummyapp.feature"

    ns, kd, nm = GeneratePatientService.identity
    assert ns == "dummyapp"   # AppConfig label
    assert kd == "service"    # decorator domain
    assert nm == "patient"    # strip 'Generate' + 'Service' via AppConfig tokens

    # Registry should have the class
    assert service_registry.resolve(GeneratePatientService.identity) is GeneratePatientService


@pytest.mark.django_db(transaction=False)
@pytest.mark.xfail(
    reason=(
        "Spec decision: explicit `name` should bypass stripping; current implementation "
        "still strips even explicit names. Marking xfail until decorator is patched accordingly."
    ),
    strict=False,
)
def test_llm_service_explicit_name_should_not_be_stripped(settings):
    # This codifies the desired behavior: explicit names should be used verbatim
    settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL = ["Service"]

    @ai_service
    class GeneratePatientServiceExplicit:
        __module__ = "tests.simcore_ai_django.fixtures.dummyapp.feature"
        name = "MyService"  # expected to be preserved without stripping

    # Desired behavior: nm == "myservice" (normalize only), NOT stripped to "my"
    ns, kd, nm = GeneratePatientServiceExplicit.identity
    assert ns == "dummyapp"
    assert kd == "service"
    assert nm == "myservice"