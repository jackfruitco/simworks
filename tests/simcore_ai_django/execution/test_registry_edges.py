import importlib
import pytest


def test_unknown_backend_falls_back_to_immediate(monkeypatch):
    # Clear, then import to trigger built-ins
    import simcore_ai_django.execution as exec_pkg
    from simcore_ai_django.execution.registry import get_backend_by_name

    b = get_backend_by_name("not-a-real-backend")
    # Should not raise; should return immediate singleton
    b2 = get_backend_by_name("immediate")
    assert b is b2


def test_duplicate_registration_last_write_wins(monkeypatch):
    from simcore_ai_django.execution.registry import register_backend, get_backend_by_name
    from simcore_ai_django.execution.types import BaseExecutionBackend

    class A(BaseExecutionBackend):
        def execute(self, *, service_cls, kwargs): return "A"
        def enqueue(self, *, service_cls, kwargs, delay_s=None, queue=None): return "A-ID"

    class B(BaseExecutionBackend):
        def execute(self, *, service_cls, kwargs): return "B"
        def enqueue(self, *, service_cls, kwargs, delay_s=None, queue=None): return "B-ID"

    register_backend("immediate", A)
    register_backend("immediate", B)  # overwrite
    inst = get_backend_by_name("immediate")
    assert isinstance(inst, B)


def test_task_backend_decorator_type_validation():
    from simcore_ai_django.execution.decorators import task_backend

    with pytest.raises(TypeError):
        @task_backend("bad")
        class NotABackend:  # not subclassing BaseExecutionBackend
            pass


def test_execution_package_does_not_export_backend_classes():
    import simcore_ai_django.execution as exec_pkg
    assert "ImmediateBackend" not in getattr(exec_pkg, "__all__", [])
    # and also not bound at top-level
    assert not hasattr(exec_pkg, "ImmediateBackend")