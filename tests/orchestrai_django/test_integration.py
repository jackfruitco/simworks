import importlib
import sys
import types
from pathlib import Path

import pytest

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

    def get_containing_app_config(module_name):
        return None

    apps_mod.get_containing_app_config = get_containing_app_config
    apps_mod.apps = apps_mod

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


def make_package(tmp_path: Path, name: str, files: dict[str, str]) -> None:
    base = tmp_path / name
    base.mkdir()
    (base / "__init__.py").write_text("")
    for rel_path, content in files.items():
        target = base / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def test_single_mode_rejects_clients_providers(monkeypatch):
    from orchestrai_django import integration

    settings_obj = types.SimpleNamespace(
        ORCA_CONFIG={
            "MODE": "single",
            "CLIENT": {"provider": "openai"},
            "CLIENTS": {"bad": {}},
        }
    )
    install_fake_django(monkeypatch, settings_obj)

    with pytest.raises(ValueError):
        integration.configure_from_django_settings()


def test_single_mode_configures_client(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    settings_obj = types.SimpleNamespace(
        ORCA_CONFIG={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=[],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    conf = integration.configure_from_django_settings(app)

    assert conf["CLIENT"]["provider"] == "stub"
    app.start()
    assert "default" in app.clients.all()


def test_identity_strip_tokens_from_django_settings(monkeypatch):
    settings_obj = types.SimpleNamespace(
        ORCA_IDENTITY_STRIP_TOKENS="Foo, Bar ,Baz",
        INSTALLED_APPS=[],
    )
    install_fake_django(monkeypatch, settings_obj)

    from orchestrai_django.identity.resolvers import DjangoIdentityResolver

    class Dummy:
        pass

    resolver = DjangoIdentityResolver()
    tokens = resolver._collect_strip_tokens(Dummy)

    assert {"Foo", "Bar", "Baz"}.issubset(set(tokens))


def test_django_discovery_prefers_orca_and_loads_components(monkeypatch, tmp_path):
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    make_package(
        tmp_path,
        "myapp",
        {
            "orca/__init__.py": "",
            "orca/services/__init__.py": "IMPORTED = True\n",
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    settings_obj = types.SimpleNamespace(
        ORCA_CONFIG={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=["myapp"],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    conf = integration.configure_from_django_settings(app)

    assert "myapp.orca.services" in conf["DISCOVERY_PATHS"]
    app.start()
    assert sys.modules["myapp.orca.services"].IMPORTED is True


def test_django_discovery_can_load_ai_convention(monkeypatch, tmp_path):
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    make_package(
        tmp_path,
        "legacyapp",
        {
            "ai/__init__.py": "",
            "ai/services/__init__.py": "AI_IMPORTED = True\n",
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    settings_obj = types.SimpleNamespace(
        ORCA_CONFIG={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=["legacyapp"],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    conf = integration.configure_from_django_settings(app)

    assert "legacyapp.ai.services" in conf["DISCOVERY_PATHS"]
    app.start()
    assert sys.modules["legacyapp.ai.services"].AI_IMPORTED is True


def test_service_from_orca_package_registers_and_runs(monkeypatch, tmp_path):
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    service_code = """
from orchestrai.decorators import service
from orchestrai.components.services.service import BaseService

@service
class RunnableService(BaseService):
    abstract = False

    async def __call__(self, *args, **kwargs):
        return "ok"
"""
    make_package(
        tmp_path,
        "svcapp",
        {
            "orca/__init__.py": "",
            "orca/services/__init__.py": service_code,
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    settings_obj = types.SimpleNamespace(
        ORCA_CONFIG={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=["svcapp"],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    integration.configure_from_django_settings(app)
    app.start()

    module = sys.modules["svcapp.orca.services"]
    assert hasattr(module, "RunnableService")
    svc = module.RunnableService()
    assert svc.abstract is False

