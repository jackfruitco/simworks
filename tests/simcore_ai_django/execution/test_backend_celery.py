import types

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def test_celery_backend_enqueue_makes_task_call(monkeypatch, DummyService):
    # If Celery backend isn't available in your env, skip
    try:
        from simcore_ai_django.execution.backends import CeleryBackend
    except Exception:
        pytest.skip("Celery backend not available in this environment")

    # Patch the Celery task apply_async
    calls = {}

    def fake_apply_async(args=None, kwargs=None, queue=None, countdown=None, priority=None):
        calls["apply_async"] = {
            "args": args,
            "kwargs": kwargs,
            "queue": queue,
            "countdown": countdown,
            "priority": priority,
        }
        return types.SimpleNamespace(id="TASK-XYZ")

    # Import the module path the backend targets
    import simcore_ai_django.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod.run_service, "apply_async", fake_apply_async)

    backend = CeleryBackend()
    task_id = backend.enqueue(service_cls=DummyService, kwargs={"user_id": 7}, delay_s=30, queue="ai-q")
    assert isinstance(task_id, str) and task_id == "TASK-XYZ"
    assert calls["apply_async"]["queue"] == "ai-q"
    assert calls["apply_async"]["countdown"] == 30

    # traceparent should be added to kwargs by the backend
    assert "traceparent" in calls["apply_async"]["kwargs"]
