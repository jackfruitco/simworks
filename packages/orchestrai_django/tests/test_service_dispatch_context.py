import pytest

from orchestrai import get_current_app
from orchestrai._state import set_current_app
from orchestrai.components.services.django import task_proxy
from orchestrai.components.services.django.task_proxy import DjangoServiceSpec, DjangoTaskProxy
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

    class DummyCall:
        def __init__(self, pk: str):
            self.id = pk
            self.pk = pk
            self.service_identity = service_identity.as_str
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
            self.openai_response_id = None
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
                return 0

            @staticmethod
            def aggregate(*args, **kwargs):
                return {"attempt__max": 0}

        def to_jsonable(self):
            return {"id": self.id, "status": self.status}

        def save(self, update_fields=None):
            self.saved_fields = update_fields

        def refresh_from_db(self):
            pass

    dummy_call = DummyCall("call-1")

    monkeypatch.setattr("orchestrai_django.tasks.ensure_service_registry", lambda app=None: DummyRegistry())
    monkeypatch.setattr(
        "orchestrai_django.tasks.ServiceCallModel.objects.select_for_update",
        lambda: type("QS", (), {"get": lambda self, pk: dummy_call})(),
    )

    result = run_service_call("call-1")

    assert autostart_calls == [True]
