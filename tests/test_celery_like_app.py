import sys
import threading
from types import ModuleType

from orchestrai import OrchestrAI, get_current_app
from orchestrai._state import set_current_app
from orchestrai.finalize import connect_on_app_finalize
from orchestrai.fixups.base import FixupStage


def test_current_app_default_created():
    set_current_app(None)
    app = get_current_app()
    assert isinstance(app, OrchestrAI)


def test_as_current_context_manager():
    set_current_app(None)
    app = OrchestrAI("ctx")
    previous = get_current_app()
    app.set_as_current()
    assert get_current_app() is app
    previous.set_as_current()
    assert get_current_app() is previous


def test_current_app_fallback_reused_across_threads():
    set_current_app(None)
    app = OrchestrAI("threaded")
    app.set_as_current()

    seen = []

    def worker():
        seen.append(get_current_app())

    try:
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    finally:
        set_current_app(None)

    assert seen == [app]


def test_setup_is_idempotent():
    app = OrchestrAI()
    app.conf.update_from_mapping({"MODE": "single"})
    app.setup()
    first_loader = app.loader
    app.setup()
    assert app.loader is first_loader
    assert app._setup_done is True


def test_default_client_uses_full_configuration():
    app = OrchestrAI()
    app.conf.update_from_mapping(
        {
            "DEFAULT_MODEL": "openai-responses:gpt-5o-mini",
            "MODE": "pod",
        }
    )

    app.setup()

    assert app.conf.get("DEFAULT_MODEL") == "openai-responses:gpt-5o-mini"
    assert app.conf.get("MODE") == "pod"


def test_finalize_callback_attaches_on_finalize():
    seen = []

    def _mark(app):
        seen.append(app.name)

    connect_on_app_finalize(_mark)
    app = OrchestrAI()
    app.finalize()
    assert app.name in seen


class DummyFixup:
    def __init__(self):
        self.setup_calls = 0
        self.autodiscover_calls = 0

    def apply(self, stage, app, **context):
        if stage == FixupStage.CONFIGURE_POST:
            self.setup_calls += 1
        if stage == FixupStage.AUTODISCOVER_PRE:
            self.autodiscover_calls += 1
            return []
        return None


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
