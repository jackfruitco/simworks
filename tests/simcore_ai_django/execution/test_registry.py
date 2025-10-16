import importlib

def test_task_backend_decorator_registers_backend():
    from simcore_ai_django.execution.registry import get_backend_by_name
    from simcore_ai_django.execution.decorators import task_backend
    from simcore_ai_django.execution.types import BaseExecutionBackend

    @task_backend("example")
    class ExampleBackend(BaseExecutionBackend):
        def execute(self, *, service_cls, kwargs):
            return "ok"
        def enqueue(self, *, service_cls, kwargs, delay_s=None, queue=None) -> str:
            return "id"

    inst = get_backend_by_name("example")
    assert isinstance(inst, ExampleBackend)
    # singleton behavior
    inst2 = get_backend_by_name("example")
    assert inst is inst2


def test_builtins_are_imported_and_registered():
    # execution.__init__ imports backends via private alias
    importlib.invalidate_caches()
    import simcore_ai_django.execution as exec_pkg
    from simcore_ai_django.execution.registry import get_backend_by_name

    # built-ins should exist
    assert get_backend_by_name("immediate")
    # celery may be optional in env; if available it will be registered
    try:
        assert get_backend_by_name("celery")
    except Exception:
        # acceptable if Celery not installed/available
        pass