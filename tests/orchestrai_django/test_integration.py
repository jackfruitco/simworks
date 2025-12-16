import importlib
import sys
import importlib
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


def test_api_facade_removed(monkeypatch):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("orchestrai_django.api")


def test_single_mode_rejects_clients_providers(monkeypatch):
    from orchestrai_django import integration

    settings_obj = types.SimpleNamespace(
        ORCHESTRAI={
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
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=[],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    conf = integration.configure_from_django_settings(app)

    assert conf["CLIENT"]["provider"] == "stub"
    app.start()
    assert "default" in app.clients.all()


def test_single_mode_exposes_app_client(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    settings_obj = types.SimpleNamespace(
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub", "name": "solo"}},
        INSTALLED_APPS=[],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    integration.configure_from_django_settings(app)

    app.start()

    assert app.client is not None
    assert app.client.get("name") == "solo"


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
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=["myapp"],
    )
    install_fake_django(monkeypatch, settings_obj)

    app = OrchestrAI()
    conf = integration.configure_from_django_settings(app)

    assert "orchestrai.contrib.provider_backends" in conf["DISCOVERY_PATHS"]
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
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub"}},
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
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub"}},
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


def test_appconfig_ready_single_client(monkeypatch, tmp_path):
    import importlib

    from orchestrai.client.registry import clear_clients, list_clients

    clear_clients()
    dummy = tmp_path / "dummy_entry.py"
    dummy.write_text(
        "from orchestrai import OrchestrAI\n"
        "from orchestrai_django.integration import configure_from_django_settings\n"
        "\n"
        "def get_app():\n"
        "    app = OrchestrAI()\n"
        "    configure_from_django_settings(app)\n"
        "    return app\n"
    )

    settings_obj = types.SimpleNamespace(
        ORCA_AUTOSTART=True,
        ORCA_ENTRYPOINT="dummy_entry:get_app",
        ORCHESTRAI={
            "MODE": "single",
            "CLIENT": {
                "provider": "openai",
                "surface": "responses",
                "api_key_envvar": "TEST_KEY",
            },
        },
        INSTALLED_APPS=[],
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    install_fake_django(monkeypatch, settings_obj)

    apps_mod = importlib.import_module("orchestrai_django.apps")
    monkeypatch.setattr(apps_mod, "_started", False)
    OrchestrAIDjangoConfig = getattr(apps_mod, "OrchestrAIDjangoConfig")

    cfg = OrchestrAIDjangoConfig("orchestrai_django")
    cfg.ready()

    assert "default" in list_clients()
    clear_clients()


def test_ready_skips_default_management_commands(monkeypatch, tmp_path):
    import orchestrai_django.apps as django_apps

    entrypoint = tmp_path / "skip_entry.py"
    entrypoint.write_text(
        "from orchestrai import OrchestrAI\n\n"
        "app = OrchestrAI()\n\n"
        "def get_app():\n"
        "    return app\n"
    )

    settings_obj = types.SimpleNamespace(
        ORCA_AUTOSTART=True,
        ORCA_ENTRYPOINT="skip_entry:get_app",
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=[],
    )

    monkeypatch.setattr(sys, "argv", ["manage.py", "migrate"])
    monkeypatch.syspath_prepend(str(tmp_path))
    install_fake_django(monkeypatch, settings_obj)

    monkeypatch.setattr(django_apps, "_started", False)
    cfg = django_apps.OrchestrAIDjangoConfig("orchestrai_django")
    cfg.ready()

    assert not hasattr(settings_obj, "_ORCHESTRAI_APP")
    assert django_apps._started is False


def test_adapter_runs_configure_before_ensure_ready(monkeypatch, tmp_path):
    import orchestrai_django.apps as django_apps
    from orchestrai import OrchestrAI
    from orchestrai_django import integration

    order: list[str] = []

    original_configure = integration.configure_from_django_settings
    original_ensure_ready = OrchestrAI.ensure_ready

    def tracking_configure(app, **kwargs):
        order.append("configure")
        return original_configure(app, **kwargs)

    def tracking_ensure_ready(self):  # type: ignore[override]
        order.append("ensure_ready")
        return original_ensure_ready(self)

    monkeypatch.setattr(integration, "configure_from_django_settings", tracking_configure)
    monkeypatch.setattr(OrchestrAI, "ensure_ready", tracking_ensure_ready)

    entrypoint = tmp_path / "ordered_entry.py"
    entrypoint.write_text(
        "from orchestrai import OrchestrAI\n\n"
        "def get_app():\n"
        "    return OrchestrAI()\n"
    )

    settings_obj = types.SimpleNamespace(
        ORCA_AUTOSTART=True,
        ORCA_ENTRYPOINT="ordered_entry:get_app",
        ORCHESTRAI={"MODE": "single", "CLIENT": {"provider": "stub"}},
        INSTALLED_APPS=[],
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    install_fake_django(monkeypatch, settings_obj)
    monkeypatch.setattr(sys, "argv", ["manage.py", "runserver"])
    monkeypatch.setattr(django_apps, "_started", False)

    cfg = django_apps.OrchestrAIDjangoConfig("orchestrai_django")
    cfg.ready()

    assert order[:2] == ["configure", "ensure_ready"]


def test_django_fixup_runs_at_autodiscover_stage(monkeypatch, tmp_path):
    import orchestrai_django.apps as django_apps
    from orchestrai.fixups.base import FixupStage
    from orchestrai_django import integration

    calls: list[str] = []
    stages: list[FixupStage] = []

    def fake_django_autodiscover(app):
        calls.append("django_autodiscover")
        return []

    original_apply = integration.DjangoAutodiscoverFixup.apply

    def tracking_apply(self, stage, app, **context):
        stages.append(stage)
        return original_apply(self, stage, app, **context)

    monkeypatch.setattr(integration, "django_autodiscover", fake_django_autodiscover)
    monkeypatch.setattr(integration.DjangoAutodiscoverFixup, "apply", tracking_apply)

    entrypoint = tmp_path / "fixup_entry.py"
    entrypoint.write_text(
        "from orchestrai import OrchestrAI\n\n"
        "def get_app():\n"
        "    return OrchestrAI()\n"
    )

    settings_obj = types.SimpleNamespace(
        ORCA_AUTOSTART=True,
        ORCA_ENTRYPOINT="fixup_entry:get_app",
        ORCHESTRAI={
            "MODE": "single",
            "CLIENT": {"provider": "stub"},
            "DISCOVERY_PATHS": [],
        },
        INSTALLED_APPS=[],
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    install_fake_django(monkeypatch, settings_obj)
    monkeypatch.setattr(sys, "argv", ["manage.py", "runserver"])
    monkeypatch.setattr(django_apps, "_started", False)

    cfg = django_apps.OrchestrAIDjangoConfig("orchestrai_django")
    cfg.ready()

    assert calls == ["django_autodiscover"]
    assert FixupStage.AUTODISCOVER_PRE in stages

