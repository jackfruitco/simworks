from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "test"
JWT_SECRET_KEY = "test-jwt-secret-key-for-tests"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.sites",
    "tests.orchestrai_django.fixtures.dummyapp",
    "orchestrai_django",  # core package under test
    # SimWorks apps for integration tests
    "apps.accounts",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.apple",
    "allauth.socialaccount.providers.google",
    "apps.common",
    "apps.simcore",
    "apps.chatlab",
    "apps.trainerlab",
    "channels",  # For WebSocket support
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
AUTH_USER_MODEL = "accounts.User"
SITE_ID = 1
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URL configuration
ROOT_URLCONF = "config.urls"

# Middleware configuration
MIDDLEWARE = [
    "apps.common.middleware.HealthCheckMiddleware",
    "apps.common.middleware.CorrelationIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Template configuration (minimal for tests)
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "SimWorks" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Channels configuration for WebSocket tests
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

# Mirror production allauth behavior for email-only user model.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": "test-google-client-id",
            "secret": "test-google-secret",
            "key": "",
        }
    },
    "apple": {
        "APP": {
            "client_id": "test-apple-client-id",
            "secret": "test-apple-team-id",
            "key": "test-apple-key-id",
            "settings": {
                "certificate_key": "test-apple-private-key",
            },
        }
    },
}
