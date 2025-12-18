import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    sync_mod = types.ModuleType("asgiref.sync")

    def sync_to_async(func):
        async def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    def async_to_sync(func):
        def wrapper(*args, **kwargs):
            import asyncio

            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return asyncio.run(result)
            return result

        return wrapper

    sync_mod.sync_to_async = sync_to_async
    sync_mod.async_to_sync = async_to_sync
    monkeypatch.setitem(sys.modules, "asgiref.sync", sync_mod)
    monkeypatch.setitem(sys.modules, "asgiref", types.SimpleNamespace(sync=sync_mod))

    django_mod = types.ModuleType("django")
    tasks_mod = types.ModuleType("django.tasks")
    base_mod = types.ModuleType("django.tasks.base")

    class DummyTask:
        pass

    base_mod.Task = DummyTask
    tasks_mod.base = base_mod
    django_mod.tasks = tasks_mod

    monkeypatch.setitem(sys.modules, "django", django_mod)
    monkeypatch.setitem(sys.modules, "django.tasks", tasks_mod)
    monkeypatch.setitem(sys.modules, "django.tasks.base", base_mod)
    yield
    for name in ("django", "django.tasks", "django.tasks.base", "asgiref", "asgiref.sync"):
        sys.modules.pop(name, None)


def test_enqueue_prefers_async_task(monkeypatch):
    from orchestrai_django.service_runners.django_tasks import DjangoTaskRunner

    class AsyncTask:
        def __init__(self):
            self.calls: list[dict] = []

        async def aenqueue(self, **payload):
            self.calls.append(payload)
            return {"runner": payload.get("runner_name"), "payload": payload}

    class Service:
        identity = SimpleNamespace(as_str="services.demo.chat.initial")

    task = AsyncTask()
    runner = DjangoTaskRunner({"services.demo.chat.initial": task})

    result = runner.enqueue(service_cls=Service, service_kwargs={"foo": "bar"}, phase="service")

    assert result["runner"] == "services.demo.chat.initial"
    assert task.calls[0]["service_kwargs"] == {"foo": "bar"}
    assert task.calls[0]["phase"] == "service"


def test_get_status_refreshes_result(monkeypatch):
    from orchestrai_django.service_runners.django_tasks import DjangoTaskRunner

    class RefreshingResult:
        def __init__(self):
            self.refreshed = False

        def refresh(self):
            self.refreshed = True

    class Service:
        identity = SimpleNamespace(as_str="services.demo.chat.initial")

    runner = DjangoTaskRunner({"services.demo.chat.initial": lambda **_payload: None})
    result = RefreshingResult()

    refreshed = runner.get_status(
        service_cls=Service,
        service_kwargs={},
        phase="service",
        runner_kwargs={"task_result": result},
    )

    assert refreshed is result
    assert result.refreshed is True
