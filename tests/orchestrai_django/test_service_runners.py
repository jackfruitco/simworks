import importlib
import sys
import types

import pytest

from orchestrai import OrchestrAI
from orchestrai.components.services.service import BaseService
from orchestrai_django import integration
from tests.orchestrai_django.test_integration import install_fake_django


class DummyService(BaseService):
    abstract = False

    async def arun(self, **ctx):
        return {"runner": "django", **ctx}


def test_django_runner_registered(monkeypatch):
    settings_obj = types.SimpleNamespace(
        ORCHESTRAI={"CLIENT": {"provider": "stub"}}, INSTALLED_APPS=[]
    )
    install_fake_django(monkeypatch, settings_obj)

    core_mod = types.ModuleType("core")
    core_models = types.ModuleType("core.models")
    core_models.PersistModel = object
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.models", core_models)

    # Ensure a clean import state for tasks helper
    if "orchestrai_django.tasks" in sys.modules:
        importlib.reload(sys.modules["orchestrai_django.tasks"])

    app = OrchestrAI().set_as_current()
    integration.configure_from_django_settings(app)

    with app.as_current():
        app.start()
        assert app.default_service_runner == "django"
        assert set(app.service_runners) >= {"local", "django"}

        captured: list[dict] = []

        def _capture_enqueue(**payload):
            captured.append(payload)
            return {"queued": True}

        monkeypatch.setattr("orchestrai_django.tasks.enqueue_service", _capture_enqueue)

        result = DummyService().task.enqueue()

        assert captured and captured[0]["service_cls"] is DummyService
        assert result == {"queued": True}
