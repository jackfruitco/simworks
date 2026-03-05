"""Shared pytest fixtures for orchestrai_django tests."""

from pathlib import Path

import django
from django.conf import settings
import pytest

_PACKAGE_TEST_ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session", autouse=True)
def django_setup():
    """Configure Django settings for tests."""
    if not settings.configured:
        settings.configure(
            INSTALLED_APPS=[
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "orchestrai_django",
            ],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            SECRET_KEY="test-secret-key",
            USE_TZ=True,
            DOMAIN_PERSIST_MAX_ATTEMPTS=10,
            DOMAIN_PERSIST_BATCH_SIZE=100,
        )
        django.setup()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = Path(str(getattr(item, "path", getattr(item, "fspath", "")))).resolve()
        if _PACKAGE_TEST_ROOT not in path.parents and path != _PACKAGE_TEST_ROOT:
            continue
        if not item.get_closest_marker("contract"):
            item.add_marker(pytest.mark.contract)
        if item.get_closest_marker("django_db") and not item.get_closest_marker("integration"):
            item.add_marker(pytest.mark.integration)
