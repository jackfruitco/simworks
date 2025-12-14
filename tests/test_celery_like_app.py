import sys
from types import ModuleType

import pytest

from orchestrai import OrchestrAI, get_current_app
from orchestrai.fixups.base import BaseFixup
from orchestrai.shared import shared_service


def test_current_app_default_created():
    app = get_current_app()
    assert isinstance(app, OrchestrAI)


def test_as_current_context_manager():
    app = OrchestrAI("ctx")
    with app.as_current():
        assert get_current_app() is app
    assert get_current_app() is not app


def test_setup_is_idempotent():
    app = OrchestrAI()
    app.conf.update_from_mapping({"CLIENT": {"name": "alpha"}})
    app.setup()
    app.setup()
    assert app.client == {"name": "alpha"}

def test_default_client_uses_full_configuration():
    app = OrchestrAI()
    app.conf.update_from_mapping(
        {
            "CLIENT": "alpha",
            "CLIENTS": {"alpha": {"name": "alpha", "token": "secret"}},
            "MODE": "pod",
        }
    )

    app.setup()

    assert app.client == {"name": "alpha", "token": "secret"}

def test_shared_service_attaches_on_finalize():
    @shared_service()
    def demo():
        return "ok"

    app = OrchestrAI()
    app.finalize()
    assert "demo" in app.services.all()
    assert app.services.get("demo")() == "ok"


class DummyFixup(BaseFixup):
    def __init__(self):
        self.setup_calls = 0
        self.autodiscover_calls = 0

    def on_setup(self, app):
        self.setup_calls += 1

    def autodiscover_sources(self, app):
        self.autodiscover_calls += 1
        return []


class RecordingLoader:
    def __init__(self):
        self.autodiscovered = []

    def read_configuration(self, app):
        return None

    def import_default_modules(self, app):
        return None

    def autodiscover(self, app, modules):
        self.autodiscovered.extend(modules)
        for module in modules:
            if module not in sys.modules:
                sys.modules[module] = ModuleType(module)
        return list(modules)


def test_loader_autodiscovery_imports_modules():
    loader = RecordingLoader()
    app = OrchestrAI(loader=loader)
    app.conf.update_from_mapping({"DISCOVERY_PATHS": ["tests.fake_mod"]})
    app.start()
    assert "tests.fake_mod" in loader.autodiscovered


def test_fixup_hooks_called(monkeypatch):
    full_path = f"{__name__}.DummyFixup"
    app = OrchestrAI(fixups=[full_path])
    app.setup()
    assert len(app.fixups) == 1
    fixup = app.fixups[0]
    assert isinstance(fixup, DummyFixup)
    assert fixup.setup_calls == 1
    app.autodiscover_components()
    assert fixup.autodiscover_calls == 1

