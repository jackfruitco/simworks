SECRET_KEY = "test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "tests.orchestrai_django.fixtures.dummyapp",
    "orchestrai_django",  # core package under test
    # SimWorks apps for integration tests
    "accounts",
    "core",
    "simulation",
    "chatlab",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
AUTH_USER_MODEL = "accounts.CustomUser"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"