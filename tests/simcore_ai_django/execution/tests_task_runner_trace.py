import types
import pytest


def test_task_wrapper_passes_traceparent_to_runner(monkeypatch):
    import simcore_ai_django.tasks as tasks_mod

    # Patch import + runner to observe params
    def fake_import_service(path: str):
        class Svc:
            def __init__(self, **kwargs): self.kwargs = kwargs
        return Svc

    captured = {}
    def fake_run_service(*, service=None, traceparent=None):
        captured["traceparent"] = traceparent
        captured["service"] = service
        return "OK"

    monkeypatch.setattr(tasks_mod, "_import_service", fake_import_service)
    monkeypatch.setattr(tasks_mod, "run_service", types.SimpleNamespace(apply_async=None, __call__=fake_run_service))

    # Simulate Celery calling the task
    result = tasks_mod.run_service_task("pkg.mod:Svc", {"user_id": 1, "traceparent": "00-abc-def-01"})
    assert result == "OK"
    assert captured["traceparent"] == "00-abc-def-01"
    assert hasattr(captured["service"], "kwargs") and captured["service"].kwargs["user_id"] == 1


def test_task_wrapper_import_error_raises_cleanly(monkeypatch):
    import simcore_ai_django.tasks as tasks_mod

    def bad_import(path: str):
        raise ImportError("nope")

    monkeypatch.setattr(tasks_mod, "_import_service", bad_import)

    with pytest.raises(ImportError):
        tasks_mod.run_service_task("pkg.mod:Svc", {"user_id": 1})