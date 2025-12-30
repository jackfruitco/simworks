import pytest

from orchestrai import get_current_app
from orchestrai.components.services.django import use_django_task_proxy
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.registry.services import ensure_service_registry


class DemoService(BaseService):
    identity = Identity("services", "demo", "chat", "initial")

    def execute(self, **payload):
        return {"echo": payload}


@pytest.fixture(scope="session")
def django_setup():
    import django
    from django.conf import settings
    from django.db import connection

    if not settings.configured:
        settings.configure(
            INSTALLED_APPS=[
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "orchestrai_django",
            ],
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
            USE_TZ=True,
            SECRET_KEY="test",  # nosec - test only
        )
    django.setup()

    from orchestrai_django.models import ServiceCallRecord

    with connection.schema_editor() as editor:
        editor.create_model(ServiceCallRecord)

    yield

    with connection.schema_editor() as editor:
        editor.delete_model(ServiceCallRecord)


@pytest.fixture()
def registered_service(django_setup):
    use_django_task_proxy()
    registry = ensure_service_registry(get_current_app())
    existing = registry.try_get(DemoService.identity)
    if existing is None:
        registry.register(DemoService, strict=False)
    return DemoService


def test_queue_override_persists_dispatch(registered_service):
    from orchestrai_django.models import ServiceCallRecord

    record = registered_service.task.using(backend="celery", queue="priority").enqueue(value=1)

    assert isinstance(record, ServiceCallRecord)
    assert record.queue == "priority"
    assert record.dispatch.get("queue") == "priority"
    assert record.status == "queued"


def test_immediate_backend_executes_inline(registered_service):
    result = registered_service.task.enqueue(foo="bar")

    assert result["status"] == "succeeded"
    assert result["result"]["echo"]["foo"] == "bar"


def test_service_call_record_jsonable(registered_service):
    from orchestrai_django.models import ServiceCallRecord

    record = registered_service.task.using(backend="celery").enqueue(count=2)

    payload = record.to_jsonable()
    assert payload["service_identity"] == registered_service.identity.as_str
    assert payload["service_kwargs"] == {}
    # Should be JSON serializable (raises if not)
    assert isinstance(payload["dispatch"], dict)
