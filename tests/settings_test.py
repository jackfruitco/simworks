SECRET_KEY = "test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "tests.simcore_ai_django.fixtures.dummyapp",
    "simcore_ai_django",  # core package under test
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True