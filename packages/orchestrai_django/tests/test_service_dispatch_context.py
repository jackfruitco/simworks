import pytest

from orchestrai.components.services.django.task_proxy import DjangoServiceSpec, DjangoTaskProxy
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity


class _DummyService(BaseService):
    identity = Identity("services", "demo", "ctx", "initial")

    def execute(self, **payload):  # pragma: no cover - not used in this test
        return payload


def test_django_service_spec_using_splits_dispatch_kwargs():
    spec = DjangoServiceSpec(_DummyService, {}, {})
    proxy = DjangoTaskProxy(spec.using(queue="priority", backend="celery", context={"x": 1}))

    service = proxy._build()
    dispatch = proxy._build_dispatch(service)

    assert isinstance(service, _DummyService)
    assert dispatch["backend"] == "celery"
    assert dispatch["queue"] == "priority"
    assert dispatch["service"] == _DummyService.identity.as_str


def test_run_service_call_triggers_autostart(monkeypatch):
    from orchestrai_django.tasks import run_service_call

    autostart_calls: list[bool] = []
    monkeypatch.setattr(
        "orchestrai_django.apps.ensure_autostarted", lambda: autostart_calls.append(True)
    )

    class DummyCall:
        def __init__(self, pk: str):
            self.id = pk
            self.pk = pk
            self.service_identity = _DummyService.identity.as_str
            self.service_kwargs = {}
            self.status = "pending"
            self.input = {}
            self.context = {}
            self.output_data = None
            self.error = None
            self.dispatch = {}
            self.backend = "immediate"
            self.queue = None
            self.task_id = None
            self.created_at = None
            self.started_at = None
            self.finished_at = None
            self.related_object_id = None
            self.correlation_id = None
            self.schema_fqn = None
            self.domain_persisted = False
            self.domain_persist_error = None
            self.domain_persist_attempts = 0
            self.successful_attempt = None
            self.provider_response_id = None
            self.provider_previous_response_id = None
            self.messages_json = []
            self.usage_json = None
            self.model_name = None
            self.input_tokens = 0
            self.output_tokens = 0
            self.total_tokens = 0

        class attempts:
            @staticmethod
            def count():
                # Force an early return path before any service execution logic.
                return 999

            def filter(self, **kwargs):
                return self

            @staticmethod
            def first():
                return None

        def to_jsonable(self):
            return {"id": self.id, "status": self.status}

        def save(self, update_fields=None):
            self.saved_fields = update_fields

        def refresh_from_db(self):
            pass

    dummy_call = DummyCall("call-1")

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "orchestrai_django.tasks.ensure_service_registry", lambda app=None: object()
    )
    monkeypatch.setattr(
        "orchestrai_django.tasks.ServiceCallModel.objects.select_for_update",
        lambda: type("QS", (), {"get": lambda self, pk: dummy_call})(),
    )
    monkeypatch.setattr("orchestrai_django.tasks.transaction.atomic", lambda: _NoopAtomic())

    run_service_call("call-1")

    assert autostart_calls == [True]


def test_ensure_autostarted_rebinds_cached_started_app(monkeypatch):
    from orchestrai_django import apps as apps_module

    cached_app = object()
    rebound: list[object] = []

    monkeypatch.setattr(apps_module, "_autostart_enabled", lambda: True)
    monkeypatch.setattr(apps_module, "_should_skip_ready_command", lambda argv: None)
    monkeypatch.setattr(apps_module, "_resolve_entrypoint", lambda: "config.orca:get_orca")
    monkeypatch.setattr(apps_module, "_started", True)
    monkeypatch.setattr(apps_module.dj_settings, "_ORCHESTRAI_APP", cached_app, raising=False)
    monkeypatch.setattr(apps_module, "set_current_app", lambda app: rebound.append(app))

    result = apps_module.ensure_autostarted()

    assert result is cached_app
    assert rebound == [cached_app]


def test_ensure_autostarted_resets_started_on_autostart_failure(monkeypatch):
    from orchestrai_django import apps as apps_module

    monkeypatch.setattr(apps_module, "_autostart_enabled", lambda: True)
    monkeypatch.setattr(apps_module, "_should_skip_ready_command", lambda argv: None)
    monkeypatch.setattr(apps_module, "_resolve_entrypoint", lambda: "config.orca:get_orca")
    monkeypatch.setattr(apps_module, "_started", False)

    def _boom(_entrypoint: str):
        raise RuntimeError("autostart boom")

    monkeypatch.setattr(apps_module, "_autostart", _boom)

    with pytest.raises(RuntimeError, match="autostart boom"):
        apps_module.ensure_autostarted()

    assert apps_module._started is False


def test_run_service_call_uses_autostart_returned_app_for_registry(monkeypatch):
    from orchestrai_django import tasks

    autostart_app = object()
    registry_apps: list[object | None] = []

    monkeypatch.setattr("orchestrai_django.apps.ensure_autostarted", lambda: autostart_app)

    class DummyCall:
        def __init__(self, pk: str):
            self.id = pk
            self.pk = pk
            self.service_identity = _DummyService.identity.as_str
            self.service_kwargs = {}
            self.status = "pending"
            self.input = {}
            self.context = {}
            self.output_data = None
            self.error = None
            self.dispatch = {}
            self.backend = "immediate"
            self.queue = None
            self.task_id = None
            self.created_at = None
            self.started_at = None
            self.finished_at = None
            self.related_object_id = None
            self.correlation_id = None
            self.schema_fqn = None
            self.domain_persisted = False
            self.domain_persist_error = None
            self.domain_persist_attempts = 0
            self.successful_attempt = None
            self.provider_response_id = None
            self.provider_previous_response_id = None
            self.messages_json = []
            self.usage_json = None
            self.model_name = None
            self.input_tokens = 0
            self.output_tokens = 0
            self.total_tokens = 0

        class attempts:
            @staticmethod
            def count():
                return 999

        def to_jsonable(self):
            return {"id": self.id, "status": self.status}

        def save(self, update_fields=None):
            self.saved_fields = update_fields

        def refresh_from_db(self):
            pass

    dummy_call = DummyCall("call-1")

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "orchestrai_django.tasks.ensure_service_registry",
        lambda app=None: (registry_apps.append(app), object())[1],
    )
    monkeypatch.setattr(
        "orchestrai_django.tasks.ServiceCallModel.objects.select_for_update",
        lambda: type("QS", (), {"get": lambda self, pk: dummy_call})(),
    )
    monkeypatch.setattr("orchestrai_django.tasks.transaction.atomic", lambda: _NoopAtomic())

    tasks.run_service_call("call-1")

    assert registry_apps == [autostart_app]
