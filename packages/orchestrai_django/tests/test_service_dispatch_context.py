import pytest

from orchestrai import get_current_app
from orchestrai._state import set_current_app
from orchestrai.components.services.django import task_proxy
from orchestrai.components.services.django.task_proxy import DjangoServiceSpec, DjangoTaskProxy
from orchestrai.components.services.execution import _STATUS_SUCCEEDED
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity


@pytest.fixture()
def minimal_django_settings():
    from django.conf import settings
    import django

    if not settings.configured:
        settings.configure(
            INSTALLED_APPS=["django.contrib.contenttypes"],
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
            USE_TZ=True,
            SECRET_KEY="test",  # nosec - test only
        )
        django.setup()
    yield


class _DummyService(BaseService):
    identity = Identity("services", "demo", "ctx", "initial")

    def execute(self, **payload):  # pragma: no cover - not used in this test
        return payload


def test_dispatch_async_binds_app_context(monkeypatch, minimal_django_settings):
    parent_app = object()
    set_current_app(parent_app)

    captured = []

    def _capture_dispatch(self: DjangoTaskProxy, call_id: str) -> None:
        captured.append(get_current_app())

    class ImmediateThread:
        def __init__(self, target, name=None, daemon=None):
            self._target = target

        def start(self):  # pragma: no cover - trivial
            self._target()

    monkeypatch.setattr(DjangoTaskProxy, "_dispatch_immediate", _capture_dispatch)
    monkeypatch.setattr(task_proxy.threading, "Thread", ImmediateThread)

    proxy = DjangoTaskProxy(DjangoServiceSpec(_DummyService, {}, {}))
    proxy._dispatch_immediate_async("abc123")

    assert captured == [parent_app]


def test_run_service_call_triggers_autostart(monkeypatch, minimal_django_settings):
    from orchestrai_django.tasks import run_service_call

    autostart_calls: list[bool] = []
    monkeypatch.setattr("orchestrai_django.apps.ensure_autostarted", lambda: autostart_calls.append(True))

    service_identity = Identity("services", "demo", "ctx", "initial")

    class DummyService:
        identity = service_identity

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def execute(self, **payload):
            return {"ok": True, **payload}

    class DummyRegistry:
        def get(self, ident):
            assert ident == service_identity
            return DummyService

    class DummyRecord:
        def __init__(self, pk: str):
            self.id = pk
            self.service_identity = service_identity.as_str
            self.service_kwargs = {}
            self.status = "pending"
            self.input = {}
            self.context = {}
            self.result = None
            self.error = None
            self.dispatch = {}
            self.backend = "immediate"
            self.queue = None
            self.task_id = None
            self.created_at = None
            self.started_at = None
            self.finished_at = None

        def as_call(self):
            class _Call:
                def __init__(self, record: "DummyRecord"):
                    self.id = record.id
                    self.status = record.status
                    self.input = record.input
                    self.context = record.context
                    self.result = record.result
                    self.error = record.error
                    self.dispatch = record.dispatch
                    self.created_at = record.created_at
                    self.started_at = record.started_at
                    self.finished_at = record.finished_at

            return _Call(self)

        def update_from_call(self, call):
            self.status = call.status
            self.input = call.input
            self.context = call.context
            self.result = call.result
            self.error = call.error
            self.dispatch = call.dispatch
            self.started_at = call.started_at
            self.finished_at = call.finished_at

        def save(self, update_fields=None):  # pragma: no cover - state already mutated
            self.saved_fields = update_fields

    dummy_record = DummyRecord("call-1")

    monkeypatch.setattr("orchestrai_django.tasks.ensure_service_registry", lambda app=None: DummyRegistry())
    monkeypatch.setattr(
        "orchestrai_django.tasks.ServiceCallRecord.objects.get", lambda pk: dummy_record
    )
    monkeypatch.setattr("orchestrai_django.tasks.to_jsonable", lambda call: {"id": call.id, "status": call.status})

    result = run_service_call("call-1")

    assert autostart_calls == [True]
    assert result["status"] == _STATUS_SUCCEEDED
