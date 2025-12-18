import types
import sys

import pytest

sys.modules.setdefault(
    "core.models",
    types.SimpleNamespace(PersistModel=type("PersistModel", (), {})),
)
sys.modules.setdefault("core", types.SimpleNamespace(models=sys.modules["core.models"]))

from orchestrai_django.components.services.services import DjangoBaseService


class DjangoContextService(DjangoBaseService):
    abstract = False
    namespace = "tests"
    kind = "service"
    name = "ctx"


def test_django_using_accepts_ctx():
    svc = DjangoContextService.using(ctx={"simulation_id": 1})

    assert svc.context["simulation_id"] == 1


def test_django_constructor_rejects_ctx_kwarg():
    with pytest.raises(TypeError):
        DjangoContextService(context={"ok": True}, ctx={"bad": True})
