# simworks/config/settings.py
import os
from pathlib import Path

from apps.common.utils.system import check_env

from . import observability_settings
from .auth_settings import (
    ACCOUNT_ADAPTER,
    ACCOUNT_EMAIL_VERIFICATION,
    ACCOUNT_FORMS,
    ACCOUNT_LOGIN_METHODS,
    ACCOUNT_LOGOUT_REDIRECT_URL,
    ACCOUNT_SIGNUP_FIELDS,
    ACCOUNT_USER_MODEL_USERNAME_FIELD,
    LOGIN_REDIRECT_URL,
    SITE_ID,
    SOCIALACCOUNT_PROVIDERS,
)
from .logging import LOGGING
from .security_settings import (
    ALLOWED_HOSTS,
    CSRF_COOKIE_SECURE,
    CSRF_TRUSTED_ORIGINS,
    DJANGO_BEHIND_PROXY,
    SECURE_HSTS_INCLUDE_SUBDOMAINS,
    SECURE_HSTS_PRELOAD,
    SECURE_HSTS_SECONDS,
    SECURE_PROXY_SSL_HEADER,
    SECURE_SSL_REDIRECT,
    SESSION_COOKIE_SECURE,
    USE_X_FORWARDED_HOST,
)
from .settings_parsers import bool_from_env, int_from_env
from .task_settings import (
    CELERY_ACCEPT_CONTENT,
    CELERY_BEAT_SCHEDULER,
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    CELERY_TASK_SERIALIZER,
    CELERY_TASK_SOFT_TIME_LIMIT,
    CELERY_TASK_TIME_LIMIT,
    CHANNEL_LAYERS,
    DJANGO_TASKS_MAX_RETRIES,
    DJANGO_TASKS_RETRY_DELAY,
    RATE_LIMIT_API_REQUESTS,
    RATE_LIMIT_AUTH_REQUESTS,
    RATE_LIMIT_MESSAGE_REQUESTS,
    REDIS_BASE,
    REDIS_HOSTNAME,
    REDIS_PASSWORD,
    REDIS_PORT,
    TASKS,
)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key claimed in production secret!
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-y2g6+*cy9ia-!v&m_s40_m%294oyunrhd3m79(jqwxek_--d(7",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = bool_from_env("DJANGO_DEBUG", default=False)

AUTH_USER_MODEL = "accounts.User"

# Application definition
INSTALLED_APPS = [
    "daphne",
    "channels",
    "apps.accounts",
    # "django_celery_beat",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "corsheaders",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.apple",
    "allauth.socialaccount.providers.google",
    "django_htmx",
    "apps.common",
    "apps.simcore",
    "apps.chatlab",
    "apps.trainerlab",
    "orchestrai_django",
    "imagekit",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "apps.common.middleware.HealthCheckMiddleware",
    "apps.common.middleware.CorrelationIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.accounts.middleware.InvitationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.common.context_processors.debug_flag",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
db_engine = os.getenv("DATABASE", "postgresql")
if db_engine == "sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
elif db_engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "AppDatabase"),
            "USER": os.getenv("DB_USER", "appuser"),
            "PASSWORD": os.getenv("DB_PASSWORD"),
            "HOST": os.getenv("DB_HOST", "db"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    raise ValueError(f"Unsupported database engine: {db_engine}")

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# CORS
CORS_ALLOWED_ORIGINS = check_env("DJANGO_CORS_ALLOWED_ORIGINS", default=CSRF_TRUSTED_ORIGINS)
CORS_ALLOWED_ORIGINS_REGEX = check_env("DJANGO_CORS_ALLOWED_ORIGINS_REGEX", default=None)
CORS_ALLOW_ALL_ORIGINS = bool_from_env("DJANGO_CORS_ALLOW_ALL_ORIGINS", default=False)

# OrchestrAI configuration
ORCA_AUTOSTART = True
ORCA_ENTRYPOINT = "config.orca:get_orca"
ORCHESTRAI = {
    "MODE": "single",
    "DEFAULT_MODEL": os.getenv("ORCA_DEFAULT_MODEL", "openai-responses:gpt-5o-mini"),
}

# JWT Configuration (for mobile API clients)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
JWT_ACCESS_TOKEN_LIFETIME = int_from_env("JWT_ACCESS_TOKEN_LIFETIME", default=3600, minimum=1)
JWT_REFRESH_TOKEN_LIFETIME = int_from_env("JWT_REFRESH_TOKEN_LIFETIME", default=604800, minimum=1)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR.parent / "static"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Media files (uploaded by users)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR.parent / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SITE_NAME = check_env("SITE_NAME")
SITE_ADMIN = {
    "NAME": check_env("SITE_ADMIN_NAME", default="SimWorks"),
    "EMAIL": check_env("SITE_ADMIN_EMAIL", default="<EMAIL>"),
}

CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"
