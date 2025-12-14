import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DJANGO_SRC = ROOT / "packages" / "orchestrai_django" / "src"
if str(DJANGO_SRC) not in sys.path:
    sys.path.insert(0, str(DJANGO_SRC))

def install_fake_django(monkeypatch, settings_obj):
    django_mod = types.ModuleType("django")

    conf_mod = types.ModuleType("django.conf")
    conf_mod.settings = settings_obj

    class DummyAppConfig:
        def __init__(self, app_name, module=None):
            self.name = app_name
            self.module = module

    apps_mod = types.ModuleType("django.apps")
    apps_mod.AppConfig = DummyAppConfig

    utils_mod = types.ModuleType("django.utils")
    module_loading_mod = types.ModuleType("django.utils.module_loading")
    module_loading_mod.calls = []

    def autodiscover_modules(*args, **kwargs):
        module_loading_mod.calls.append((args, kwargs))

    module_loading_mod.autodiscover_modules = autodiscover_modules
    utils_mod.module_loading = module_loading_mod

    django_mod.conf = conf_mod
    django_mod.apps = apps_mod
    django_mod.utils = utils_mod

    monkeypatch.setitem(sys.modules, "django", django_mod)
    monkeypatch.setitem(sys.modules, "django.conf", conf_mod)
    monkeypatch.setitem(sys.modules, "django.apps", apps_mod)
    monkeypatch.setitem(sys.modules, "django.utils", utils_mod)
    monkeypatch.setitem(sys.modules, "django.utils.module_loading", module_loading_mod)

    return DummyAppConfig, module_loading_mod


def test_configure_from_django_settings_prefers_mapping(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    settings_obj = types.SimpleNamespace(
        ORCA_CONFIG={"CLIENT": "default", "CLIENTS": {"default": {"provider": "openai"}}}
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    conf = integration.configure_from_django_settings(app)

    assert conf["CLIENT"] == "default"
    assert app.conf["CLIENTS"] == {"default": {"provider": "openai"}}


def test_configure_from_django_settings_legacy_namespace(monkeypatch):
    from orchestrai_django import integration

    settings_obj = types.SimpleNamespace(ORCA_CLIENTS={"legacy": {"provider": "stub"}})
    install_fake_django(monkeypatch, settings_obj)

    conf = integration.configure_from_django_settings()
    assert conf["CLIENTS"] == {"legacy": {"provider": "stub"}}


def test_ready_autostarts_and_stores_app(monkeypatch):
    settings_obj = types.SimpleNamespace(
        ORCA_AUTOSTART=True,
        ORCA_ENTRYPOINT="tests.fake_entrypoint:get_orca",
    )
    DummyAppConfig, _ = install_fake_django(monkeypatch, settings_obj)

    class FakeApp:
        def __init__(self):
            self.starts = 0

        def start(self):
            self.starts += 1

    fake_app = FakeApp()
    entrypoint_mod = types.ModuleType("tests.fake_entrypoint")
    entrypoint_mod.get_orca = lambda: fake_app
    monkeypatch.setitem(sys.modules, "tests.fake_entrypoint", entrypoint_mod)

    apps_module = importlib.reload(importlib.import_module("orchestrai_django.apps"))
    monkeypatch.setattr(apps_module, "_started", False)

    cfg = apps_module.OrchestrAIDjangoConfig("orchestrai_django", apps_module)
    cfg.ready()

    assert getattr(settings_obj, "_ORCA_APP", None) is fake_app
    assert fake_app.starts == 1
