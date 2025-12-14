import importlib

import pytest

from orchestrai import OrchestrAI
from orchestrai.components.services.service import BaseService
from orchestrai.decorators import service


@service(namespace="chatlab", kind="standardized_patient", name="initial")
class RegistryService(BaseService):
    abstract = False

    def execute(self):
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def _reset_service_registry():
    # ensure per-test isolation for identity registry used by decorator
    from orchestrai.registry.singletons import services as service_registry

    service_registry._store.clear()
    service_registry.register(RegistryService)
    yield
    service_registry._store.clear()


def test_service_resolution_prefers_registry(monkeypatch):
    calls: list[str] = []
    real_import = importlib.import_module

    def tracking_import(name, *args, **kwargs):
        calls.append(name)
        if name == "chatlab.standardized_patient":
            raise AssertionError("service identity should not be imported for resolution")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", tracking_import)

    app = OrchestrAI("core")
    app.set_as_current()
    app.ensure_ready()

    resolved = app.services.get("chatlab.standardized_patient.initial")
    assert resolved is RegistryService

    result = app.services.start("chatlab.standardized_patient.initial")
    assert result == {"status": "ok"}

    assert "chatlab.standardized_patient" not in calls
