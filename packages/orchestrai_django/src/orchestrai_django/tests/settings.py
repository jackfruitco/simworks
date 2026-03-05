SECRET_KEY = "orchestrai-django-tests"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "orchestrai_django",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

ROOT_URLCONF = "orchestrai_django.tests.urls"

DOMAIN_PERSIST_MAX_ATTEMPTS = 10
DOMAIN_PERSIST_BATCH_SIZE = 100
