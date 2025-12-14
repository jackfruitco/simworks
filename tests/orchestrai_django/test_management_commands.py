from __future__ import annotations

import importlib
import io
import sys
import textwrap
import types

import pytest


def install_fake_django_management(monkeypatch, settings_obj=None):
    django_mod = types.ModuleType("django")

    conf_mod = types.ModuleType("django.conf")
    conf_mod.settings = settings_obj or types.SimpleNamespace()

    core_mod = types.ModuleType("django.core")
    management_mod = types.ModuleType("django.core.management")
    base_mod = types.ModuleType("django.core.management.base")

    class BaseCommand:
        def __init__(self):
            self.stdout = io.StringIO()
            self.style = types.SimpleNamespace(
                SUCCESS=lambda msg: msg,
                WARNING=lambda msg: msg,
                ERROR=lambda msg: msg,
            )

        def add_arguments(self, parser):  # pragma: no cover - only needed for Django parser
            return None

    class CommandError(Exception):
        pass

    base_mod.BaseCommand = BaseCommand
    base_mod.CommandError = CommandError
    management_mod.base = base_mod
    core_mod.management = management_mod
    django_mod.core = core_mod
    django_mod.conf = conf_mod

    monkeypatch.setitem(sys.modules, "django", django_mod)
    monkeypatch.setitem(sys.modules, "django.conf", conf_mod)
    monkeypatch.setitem(sys.modules, "django.core", core_mod)
    monkeypatch.setitem(sys.modules, "django.core.management", management_mod)
    monkeypatch.setitem(sys.modules, "django.core.management.base", base_mod)

    return conf_mod.settings


def test_run_service_executes_registered_service(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai.components.services.service import BaseService

    install_fake_django_management(monkeypatch)

    app = OrchestrAI()
    app.set_as_current()

    class SimpleService(BaseService):
        abstract = False

        def execute(self):
            return {"ok": True, "ctx": dict(self.context)}

        async def aexecute(self):  # pragma: no cover - async path tested separately
            return {"ok": True, "ctx": dict(self.context)}

    SimpleService._IdentityMixin__identity_cached = types.SimpleNamespace(as_str="tests.simple")

    app.services.register("simple", SimpleService)

    from orchestrai_django.management.commands import run_service

    cmd = run_service.Command()
    cmd.handle(service="simple", context='{"foo": "bar"}', mode="start")

    output = cmd.stdout.getvalue()
    assert "executed successfully" in output
    assert "\"foo\": \"bar\"" in output


def test_run_service_supports_async_mode(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai.components.services.service import BaseService

    install_fake_django_management(monkeypatch)

    app = OrchestrAI()
    app.set_as_current()

    class AsyncService(BaseService):
        abstract = False

        def execute(self):
            return {"sync": True}

        async def aexecute(self):
            return {"async": True}

    AsyncService._IdentityMixin__identity_cached = types.SimpleNamespace(as_str="tests.async")

    app.services.register("async_service", AsyncService)

    from orchestrai_django.management.commands import run_service

    cmd = run_service.Command()
    cmd.handle(service="async_service", context="{}", mode="astart")

    output = cmd.stdout.getvalue()
    assert "async_service" in output
    assert "async" in output


def test_run_service_discovers_and_resolves_registry_identity(monkeypatch, tmp_path):
    from orchestrai import OrchestrAI
    from orchestrai.components.services.service import BaseService
    from orchestrai_django.decorators import service

    settings = install_fake_django_management(monkeypatch)

    module_dir = tmp_path / "demo_pkg"
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text("")
    (module_dir / "svc_mod.py").write_text(
        """
from orchestrai_django.decorators import service
from orchestrai.components.services.service import BaseService


@service(namespace="chatlab", kind="standardized_patient", name="initial")
class DiscoveredService(BaseService):
    abstract = False

    def execute(self):
        return {"source": "registry"}
"""
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    app = OrchestrAI()
    app.conf.update_from_mapping({"DISCOVERY_PATHS": ["demo_pkg.svc_mod"]})
    app.set_as_current()

    from orchestrai_django.management.commands import run_service

    import importlib

    calls: list[str] = []
    real_import = importlib.import_module

    def tracking_import(name, *args, **kwargs):
        calls.append(name)
        if name == "chatlab.standardized_patient.initial":
            raise AssertionError("service identity should not be imported as a module path")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", tracking_import)

    cmd = run_service.Command()
    cmd.handle(service="chatlab.standardized_patient.initial", context="{}", mode="start")

    output = cmd.stdout.getvalue()
    assert "executed successfully" in output
    assert "registry" in output
    assert "chatlab.standardized_patient.initial" not in calls


def test_run_service_supports_dry_run(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai.components.services.service import BaseService

    install_fake_django_management(monkeypatch)

    app = OrchestrAI()
    app.set_as_current()

    class DryRunService(BaseService):
        abstract = False
        seen_context: dict | None = None
        seen_dry_run: bool | None = None

        @classmethod
        def using(cls, **overrides):
            instance = super().using(**overrides)
            cls.seen_context = dict(getattr(instance, "context", {}))
            cls.seen_dry_run = instance.dry_run
            return instance

        def execute(self):
            return {"dry_run": self.dry_run}

    DryRunService._IdentityMixin__identity_cached = types.SimpleNamespace(
        as_str="tests.dry_run",
    )
    app.services.register("dry_run_service", DryRunService)

    from orchestrai_django.management.commands import run_service

    cmd = run_service.Command()
    cmd.handle(service="dry_run_service", context="{}", mode="start", dry_run=True)

    output = cmd.stdout.getvalue()
    assert "executed successfully" in output
    assert DryRunService.seen_dry_run is True
    assert DryRunService.seen_context == {}
    assert "\"dry_run\": true" in output


def test_autostart_sets_current_app_for_run_service(monkeypatch, tmp_path):
    from orchestrai import get_current_app
    from orchestrai.components.services.service import BaseService

    settings_obj = types.SimpleNamespace(
        ORCA_ENTRYPOINT="autostart_pkg.entry:get_app",
        ORCA_AUTOSTART=True,
    )

    settings = install_fake_django_management(monkeypatch, settings_obj)

    apps_mod = types.ModuleType("django.apps")

    class DummyAppConfig:
        def __init__(self, app_name, module=None):
            self.name = app_name
            self.module = module

    apps_mod.AppConfig = DummyAppConfig
    monkeypatch.setitem(sys.modules, "django.apps", apps_mod)

    pkg_dir = tmp_path / "autostart_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "entry.py").write_text(
        textwrap.dedent(
            """
            from orchestrai import OrchestrAI
            from orchestrai.components.services.service import BaseService

            autostart_app = OrchestrAI()

            class AutostartService(BaseService):
                abstract = False

                def execute(self):
                    return {"from_autostart": True}

            autostart_app.services.register("autostart.service", AutostartService)
            autostart_app.conf.update_from_mapping(
                {"CLIENT": {"name": "auto_client", "provider": "stub"}}
            )
            autostart_app.clients.register(
                "auto_client", {"name": "auto_client", "provider": "stub"}
            )

            def get_app():
                return autostart_app
            """
        )
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    import orchestrai_django.apps as django_apps

    monkeypatch.setattr(django_apps, "_started", False)

    config = django_apps.OrchestrAIDjangoConfig("orchestrai_django", module="orchestrai_django")
    config.ready()

    autostart_mod = importlib.import_module("autostart_pkg.entry")
    app = autostart_mod.autostart_app

    assert settings._ORCA_APP is app
    assert get_current_app() is app
    assert app.clients.get("auto_client") == {"name": "auto_client", "provider": "stub"}

    from orchestrai_django.management.commands import run_service

    cmd = run_service.Command()
    cmd.handle(service="autostart.service", context="{}", mode="start")

    output = cmd.stdout.getvalue()
    assert "executed successfully" in output

    report = app.component_report_text()
    assert "autostart.service" in report
    assert "auto_client" in report


def test_run_service_missing_identity_has_clear_error(monkeypatch):
    from orchestrai import OrchestrAI
    from orchestrai_django.management.commands import run_service

    install_fake_django_management(monkeypatch)

    app = OrchestrAI()
    app.set_as_current()

    cmd = run_service.Command()
    with pytest.raises(run_service.CommandError) as excinfo:
        cmd.handle(service="chatlab.standardized_patient.initial", context="{}", mode="start")

    message = str(excinfo.value)
    assert "chatlab.standardized_patient.initial" in message
    assert "ensure discovery" in message


def test_ai_healthcheck_runs_against_current_app(monkeypatch):
    from orchestrai import OrchestrAI

    install_fake_django_management(monkeypatch)

    app = OrchestrAI()
    app.set_as_current()

    import orchestrai_django.management.commands.ai_healthcheck as ai_cmd

    monkeypatch.setattr(ai_cmd, "healthcheck_all_registered", lambda: {"default": (True, "ok")})

    class DummyBackend:
        name = "dummy"

    class DummyClient:
        backend = DummyBackend()

    monkeypatch.setattr(ai_cmd, "list_clients", lambda: {"default": DummyClient()})
    monkeypatch.setattr(ai_cmd.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    cmd = ai_cmd.Command()
    with pytest.raises(SystemExit) as excinfo:
        cmd.handle(json=True, flat=True)

    assert excinfo.value.code == 0
