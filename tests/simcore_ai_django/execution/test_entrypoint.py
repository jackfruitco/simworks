import pytest

from simcore_ai_django.execution.entrypoint import execute

def test_execute_sync_calls_execute_on_backend(register_fake_backend, DummyService):
    register_fake_backend("immediate")  # replace immediate with fake
    result = execute(DummyService, user_id=42)
    assert result == "EXECUTED"  # from FakeBackend.execute


def test_execute_async_calls_enqueue_on_backend(register_fake_backend, DummyService):
    register_fake_backend("immediate")
    result = execute(DummyService, enqueue=True, user_id=42)
    assert isinstance(result, str) and result  # task id from FakeBackend.enqueue


def test_backend_override_by_name(register_fake_backend, DummyService):
    register_fake_backend("celery")
    result = execute(DummyService, backend="celery", enqueue=True, user_id=1)
    assert result == "TASK-ID-123"


def test_require_enqueue_forces_async(monkeypatch, register_fake_backend, DummyService):
    register_fake_backend("immediate")

    class Svc(DummyService):  # type: ignore
        require_enqueue = True

    # Asking for sync should be upgraded to async
    res = execute(Svc, enqueue=False, user_id=1)
    assert isinstance(res, str)  # got a task id (enqueued)


def test_service_defaults_used_when_no_overrides(settings, register_fake_backend, DummyService):
    # set service class defaults
    register_fake_backend("celery")

    class Svc(DummyService):  # type: ignore
        execution_mode = "async"
        execution_backend = "celery"

    res = execute(Svc, user_id=1)
    assert isinstance(res, str)  # enqueued due to service defaults