import importlib

import pytest

from orchestrai import OrchestrAI
from orchestrai.client.registry import clear_clients
from orchestrai.client.settings_loader import ClientSettings
from orchestrai.components.services.exceptions import ServiceConfigError
from orchestrai.components.services.service import BaseService
from orchestrai.decorators import service
from orchestrai.identity.domains import SERVICES_DOMAIN


@service(namespace="chatlab", group="standardized_patient", name="initial")
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
        if name == "services.chatlab.standardized_patient":
            raise AssertionError("service identity should not be imported for resolution")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", tracking_import)

    app = OrchestrAI("core")
    app.set_as_current()
    app.ensure_ready()

    resolved = app.services.get("services.chatlab.standardized_patient.initial")
    assert resolved is RegistryService

    result = app.services.start("services.chatlab.standardized_patient.initial")
    assert result == {"status": "ok"}

    assert "services.chatlab.standardized_patient" not in calls


def test_service_resolution_error_points_to_single_mode(monkeypatch):
    class DummyService(BaseService):
        abstract = False

        def execute(self):
            return None

    clear_clients()
    monkeypatch.setattr(
        "orchestrai.client.factory.load_client_settings",
        lambda mapping=None: ClientSettings.from_mapping({"MODE": "single", "CLIENT": None}),
    )

    svc = DummyService()

    with pytest.raises(ServiceConfigError) as excinfo:
        svc.get_client()

    assert "ORCA_CONFIG['CLIENT']" in str(excinfo.value)

    clear_clients()
