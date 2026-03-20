import asyncio

import pytest

from orchestrai import get_current_app
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.registry.services import ensure_service_registry
from orchestrai_django.task_proxy import DjangoTaskProxy, use_django_task_proxy

pytestmark = pytest.mark.django_db(transaction=True)


class DemoService(BaseService):
    identity = Identity("services", "demo", "chat", "initial")

    def execute(self, **payload):
        return {"echo": payload}


@pytest.fixture()
def registered_service(db):
    use_django_task_proxy()
    registry = ensure_service_registry(get_current_app())
    existing = registry.try_get(DemoService.identity)
    if existing is None:
        registry.register(DemoService, strict=False)
    return DemoService


def test_queue_override_persists_dispatch(registered_service):
    from orchestrai_django.models import ServiceCall

    task_id = registered_service.task.using(backend="celery", queue="priority").enqueue(value=1)

    record = ServiceCall.objects.get(pk=task_id)
    assert record.queue == "priority"
    assert record.dispatch.get("queue") == "priority"
    assert record.status == "queued"


def test_immediate_backend_dispatches_fire_and_forget(monkeypatch, registered_service):
    from orchestrai_django.models import ServiceCall

    dispatched: list[str] = []

    def _capture_dispatch(self: DjangoTaskProxy, call_id: str) -> None:
        dispatched.append(call_id)

    monkeypatch.setattr(DjangoTaskProxy, "_dispatch_immediate", _capture_dispatch)

    task_id = registered_service.task.enqueue(foo="bar")

    assert dispatched == [task_id]
    record = ServiceCall.objects.get(pk=task_id)
    assert record.status == "pending"


def test_service_call_jsonable(registered_service):
    from orchestrai_django.models import ServiceCall

    task_id = registered_service.task.using(backend="celery").enqueue(count=2)
    record = ServiceCall.objects.get(pk=task_id)

    payload = record.to_jsonable()
    assert payload["service_identity"] == registered_service.identity.as_str
    assert payload["status"] in {"queued", "pending", "in_progress"}
    assert payload["backend"] == "celery"
    # Should be JSON serializable (raises if not)
    assert isinstance(payload, dict)


@pytest.mark.asyncio
async def test_async_enqueue_uses_async_orm(registered_service):
    from orchestrai_django.models import ServiceCall

    task_id = await registered_service.task.using(backend="celery", queue="priority").aenqueue(
        value=1
    )

    fetched = await ServiceCall.objects.aget(id=task_id)
    assert fetched.queue == "priority"
    assert fetched.dispatch.get("queue") == "priority"
    assert fetched.status == "queued"


@pytest.mark.asyncio
async def test_aenqueue_shielded_from_cancellation(monkeypatch, registered_service):
    from orchestrai_django.models import ServiceCall

    dispatched: list[str] = []
    dispatched_event = asyncio.Event()

    def _capture_dispatch(self: DjangoTaskProxy, call_id: str) -> None:
        dispatched.append(call_id)
        dispatched_event.set()

    monkeypatch.setattr(DjangoTaskProxy, "_dispatch_immediate", _capture_dispatch)

    task = asyncio.create_task(registered_service.task.aenqueue())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(dispatched_event.wait(), timeout=1)
    saved = await ServiceCall.objects.aget(id=dispatched[0])
    assert saved.status == "pending"
