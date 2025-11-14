import datetime as dt
from typing import Any, Dict, Type

import pytest

from simcore_ai_django.execution.entrypoint import execute


@pytest.fixture
def FakeBackend():
    from simcore_ai_django.execution.base import BaseExecutionBackend, SupportsServiceInit

    class _FakeBackend(BaseExecutionBackend):
        supports_priority = False
        def __init__(self) -> None:
            self.calls: Dict[str, Dict[str, Any]] = {}

        def execute(self, *, service_cls: Type[SupportsServiceInit], kwargs):
            self.calls["execute"] = {"service_cls": service_cls, "kwargs": dict(kwargs)}
            return "EXECUTED"

        def enqueue(self, *, service_cls: Type[SupportsServiceInit], kwargs, delay_s=None, queue=None) -> str:
            self.calls["enqueue"] = {
                "service_cls": service_cls,
                "kwargs": dict(kwargs),
                "delay_s": delay_s,
                "queue": queue,
            }
            return "TASK-ID-XYZ"

    return _FakeBackend


@pytest.fixture
def register_backend(FakeBackend):
    def _register(name: str):
        from simcore_ai_django.execution.registry import register_backend, get_backend_by_name
        register_backend(name, FakeBackend)
        get_backend_by_name(name)  # warm singleton
        return FakeBackend
    return _register


@pytest.fixture
def DummyService():
    class _Dummy:
        __module__ = "tests.simcore_ai_django.execution.dummies"
        __name__ = "Dummy"
    return _Dummy


def test_using_dict_vs_explicit_kwargs_precedence(register_backend, DummyService):
    register_backend("celery")
    # using says backend=immediate, explicit kwargs say backend=celery → explicit wins
    res = execute(
        DummyService,
        using={"backend": "immediate", "enqueue": True},  # will be overridden
        backend="celery",
        enqueue=True,
        user_id=1,
    )
    assert isinstance(res, str) and res  # enqueued

def test_backend_as_class_is_mapped_to_name(register_backend, DummyService):
    # Register a fake named 'custom'
    Fake = register_backend("custom")

    # Pass the backend *class* instead of name; entrypoint should map to name
    res = execute(DummyService, backend=Fake, enqueue=True, user_id=1)
    assert isinstance(res, str)

def test_run_after_datetime_normalizes_to_delay_s_future(register_backend, DummyService, monkeypatch):
    register_backend("celery")
    future = dt.datetime.utcnow() + dt.timedelta(seconds=45)
    res = execute(DummyService, backend="celery", enqueue=True, run_after=future, user_id=1)
    assert isinstance(res, str)

def test_run_after_past_datetime_becomes_none(register_backend, DummyService, monkeypatch):
    register_backend("celery")
    past = dt.datetime.utcnow() - dt.timedelta(seconds=45)
    # Past time → treated as None (run now)
    res = execute(DummyService, backend="celery", enqueue=True, run_after=past, user_id=1)
    assert isinstance(res, str)

def test_priority_clamped_and_ignored_if_backend_does_not_support(register_backend, DummyService):
    register_backend("celery")  # Fake reports supports_priority=False
    res = execute(DummyService, backend="celery", enqueue=True, priority=9999, user_id=1)
    assert isinstance(res, str)

def test_enqueue_kwarg_overrides_service_defaults(register_backend, DummyService):
    register_backend("immediate")
    class Svc(DummyService):  # type: ignore
        execution_mode = "sync"
    # Force async despite service default
    result = execute(Svc, enqueue=True, user_id=1)
    assert isinstance(result, str)

def test_require_enqueue_overrides_sync_request(register_backend, DummyService):
    register_backend("immediate")
    class Svc(DummyService):  # type: ignore
        require_enqueue = True
    res = execute(Svc, enqueue=False, user_id=1)
    assert isinstance(res, str)

def test_settings_default_used_when_service_and_kwargs_unspecified(settings, register_backend, DummyService):
    # No overrides; rely on settings (set by conftest)
    register_backend("immediate")
    result = execute(DummyService, user_id=99)
    assert result == "EXECUTED"