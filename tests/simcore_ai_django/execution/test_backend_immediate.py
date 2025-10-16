def test_immediate_backend_registered_and_usable():
    # just ensure it is in registry and returns a singleton
    from simcore_ai_django.execution.registry import get_backend_by_name
    b1 = get_backend_by_name("immediate")
    b2 = get_backend_by_name("immediate")
    assert b1 is b2
    assert hasattr(b1, "supports_priority")
    assert b1.supports_priority is False


def test_immediate_enqueue_calls_runner(monkeypatch):
    from simcore_ai_django.execution.backends.immediate import ImmediateBackend

    calls = {"run": 0}
    # Patch runner.run_service so we don't actually execute anything
    import simcore_ai_django.runner as runner_mod
    def fake_run_service(**kwargs):
        calls["run"] += 1
        return "OK"

    monkeypatch.setattr(runner_mod, "run_service", fake_run_service)

    class Dummy:
        __module__ = "tests.simcore_ai_django.execution.dummies"
        __name__ = "Dummy"

    b = ImmediateBackend()

    # enqueue falls back to immediate run (per your backend)
    task_id = b.enqueue(service_cls=Dummy, kwargs={"user_id": 1}, delay_s=None, queue=None)
    assert task_id == "immediate"
    assert calls["run"] == 1


def test_immediate_execute_calls_runner(monkeypatch):
    from simcore_ai_django.execution.backends.immediate import ImmediateBackend
    calls = {"run": 0}
    import simcore_ai_django.runner as runner_mod
    def fake_run_service(**kwargs):
        calls["run"] += 1
        return "OK"

    monkeypatch.setattr(runner_mod, "run_service", fake_run_service)

    class Dummy:
        __module__ = "tests.simcore_ai_django.execution.dummies"
        __name__ = "Dummy"

    b = ImmediateBackend()
    res = b.execute(service_cls=Dummy, kwargs={"user_id": 1})
    assert res == "OK"
    assert calls["run"] == 1
