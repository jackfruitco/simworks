"""Shared pytest fixtures for orchestrai_django tests."""

import pytest
import django
from django.conf import settings


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
