import importlib
import types
from typing import Any, Dict, Type

import pytest

# Settings defaults for the execution layer
@pytest.fixture(autouse=True)
def ai_exec_settings(settings):
    settings.AI_EXECUTION_BACKENDS = {
        "DEFAULT_BACKEND": "immediate",
        "DEFAULT_MODE": "sync",
        # "CELERY": {"queue_default": "ai-default"},  # optional
    }
    return settings


# Reset backend registry between tests to avoid cross-test bleed
@pytest.fixture(autouse=True)
def reset_backend_registry():
    from simcore_ai_django.execution import registry as _reg

    _reg._BACKEND_REGISTRY.clear()
    _reg._BACKEND_SINGLETONS.clear()

    # Re-import built-ins so @task_backend decorators run again
    importlib.invalidate_caches()
    importlib.import_module("simcore_ai_django.execution")  # pulls in backends via __init__


# A tiny fake backend for asserting entrypoint routing without running services
@pytest.fixture
def FakeBackend():
    from simcore_ai_django.execution.base import BaseExecutionBackend, SupportsServiceInit

    class _FakeBackend(BaseExecutionBackend):
        supports_priority = False

        def __init__(self) -> None:
            self.calls: Dict[str, Dict[str, Any]] = {}

        def execute(self, *, service_cls: Type[SupportsServiceInit], kwargs):
            self.calls["execute"] = {
                "service_cls": service_cls,
                "kwargs": dict(kwargs),
            }
            return "EXECUTED"

        def enqueue(self, *, service_cls: Type[SupportsServiceInit], kwargs, delay_s=None, queue=None) -> str:
            self.calls["enqueue"] = {
                "service_cls": service_cls,
                "kwargs": dict(kwargs),
                "delay_s": delay_s,
                "queue": queue,
            }
            return "TASK-ID-123"

    return _FakeBackend


@pytest.fixture
def register_fake_backend(FakeBackend):
    def _register(name: str = "immediate"):
        from simcore_ai_django.execution.registry import register_backend, get_backend_by_name

        register_backend(name, FakeBackend)
        # warm singleton
        get_backend_by_name(name)
        return FakeBackend
    return _register


# A minimal dummy Service class for identity purposes (we never actually run it)
@pytest.fixture
def DummyService():
    # Avoid importing real bases: we only need a class type with module/name
    class _DummyService:
        __module__ = "tests.simcore_ai_django.execution.dummies"
        __name__ = "DummyService"

    return _DummyService

@pytest.fixture(autouse=True)
def dummy_test_app(settings):
    """
    Ensure a dummy Django app is registered during Django-identity tests.
    """
    from django.apps import apps
    from tests.simcore_ai_django.fixtures.dummyapp.apps import DummyappConfig

    if "tests.simcore_ai_django.fixtures.dummyapp" not in settings.INSTALLED_APPS:
        settings.INSTALLED_APPS += ["tests.simcore_ai_django.fixtures.dummyapp"]

    # Explicitly register if not already loaded
    if not apps.is_installed("tests.simcore_ai_django.fixtures.dummyapp"):
        apps.app_configs["dummyapp"] = DummyappConfig("tests.simcore_ai_django.fixtures.dummyapp", None)
        apps.app_configs["dummyapp"].ready()
        apps.clear_cache()

    yield
    # Teardown not usually required; Django test runner resets apps between tests