import importlib
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REMOVED_SERVICE_RUNNER_MESSAGE = (
    "Service runners have been removed. Use BaseService.task.run/arun or the Django task proxy."
)

SERVICE_RUNNER_PACKAGE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "orchestrai_django"
    / "components"
)

MODULE_NAMES = [
    "orchestrai_django.components.service_runners",
    "orchestrai_django.components.service_runners.django_tasks",
]


def _clear_service_runner_modules() -> None:
    for module_name in MODULE_NAMES:
        sys.modules.pop(module_name, None)


@pytest.fixture(autouse=True)
def stub_components_package():
    _clear_service_runner_modules()
    original_components = sys.modules.pop("orchestrai_django.components", None)

    stub = ModuleType("orchestrai_django.components")
    stub.__path__ = [str(SERVICE_RUNNER_PACKAGE_PATH)]
    sys.modules["orchestrai_django.components"] = stub

    yield

    for name in ["orchestrai_django.components", *MODULE_NAMES]:
        sys.modules.pop(name, None)
    if original_components is not None:
        sys.modules["orchestrai_django.components"] = original_components


def test_package_import_raises_immediately():
    with pytest.raises(RuntimeError, match=re.escape(REMOVED_SERVICE_RUNNER_MESSAGE)):
        importlib.import_module("orchestrai_django.components.service_runners")


def test_django_tasks_import_raises_immediately():
    with pytest.raises(RuntimeError, match=re.escape(REMOVED_SERVICE_RUNNER_MESSAGE)):
        importlib.import_module("orchestrai_django.components.service_runners.django_tasks")


def test_direct_class_import_is_blocked():
    with pytest.raises(RuntimeError, match=re.escape(REMOVED_SERVICE_RUNNER_MESSAGE)):
        from orchestrai_django.components.service_runners import (  # type: ignore # noqa: F401
            DjangoTaskServiceRunner,
        )
