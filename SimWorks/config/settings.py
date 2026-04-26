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
from .billing_settings import (
    BILLING_APPLE_PRODUCT_PLAN_MAP,
    BILLING_STRIPE_CHECKOUT_ENABLED,
    BILLING_STRIPE_PORTAL_ENABLED,
    BILLING_STRIPE_PRICE_PLAN_MAP,
    BILLING_STRIPE_PROMO_COUPON_ID,
    BILLING_STRIPE_RETURN_BASE_URL,
    BILLING_STRIPE_SECRET_KEY,
    BILLING_STRIPE_TRIAL_DAYS,
    BILLING_STRIPE_WEBHOOK_SECRET,
)
from .email_settings import (
    ACCOUNT_DEFAULT_HTTP_PROTOCOL,
    DEFAULT_FROM_EMAIL,
    EMAIL_BACKEND,
    EMAIL_BASE_URL,
    EMAIL_ENVIRONMENT_NAME,
    EMAIL_HOST,
    EMAIL_HOST_PASSWORD,
    EMAIL_HOST_USER,
    EMAIL_PORT,
    EMAIL_REPLY_TO,
    EMAIL_STAGING_BANNER_ENABLED,
    EMAIL_STAGING_SUBJECT_PREFIX,
    EMAIL_SUBJECT_PREFIX,
    EMAIL_USE_CONSOLE_BACKEND,
    EMAIL_USE_SSL,
    EMAIL_USE_TLS,
    SERVER_EMAIL,
)
from .logging import LOGGING
from .privacy_settings import (
    PRIVACY_ANALYTICS_ENABLED,
    PRIVACY_ANALYTICS_REQUIRE_CONSENT,
    PRIVACY_CHAT_RETENTION_DAYS,
    PRIVACY_DELETE_EXPORT_TOKEN_TTL_SECONDS,
    PRIVACY_DERIVED_FEEDBACK_RETENTION_DAYS,
    PRIVACY_ENABLE_BASIC_PII_SCAN,
    PRIVACY_ENABLE_PII_WARNING,
    PRIVACY_PERSIST_AI_MESSAGE_HISTORY,
    PRIVACY_PERSIST_PROVIDER_RAW,
    PRIVACY_PERSIST_RAW_AI_REQUESTS,
    PRIVACY_PERSIST_RAW_AI_RESPONSES,
    PRIVACY_RAW_AI_RETENTION_DAYS,
)
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
from .settings_parsers import bool_from_env, int_from_env, optional_int_from_env
from .task_settings import (
    CELERY_ACCEPT_CONTENT,
    CELERY_BEAT_SCHEDULER,
    CELERY_BROKER_URL,
    CELERY_RESULT_ACCEPT_CONTENT,
    CELERY_RESULT_BACKEND,
    CELERY_RESULT_SERIALIZER,
    CELERY_TASK_SERIALIZER,
    CELERY_TASK_SOFT_TIME_LIMIT,
    CELERY_TASK_TIME_LIMIT,
    CHANNEL_LAYERS,
    DJANGO_TASKS_MAX_RETRIES,
    DJANGO_TASKS_RETRY_DELAY,
    RATE_LIMIT_API_REQUESTS,
    RATE_LIMIT_AUTH_REQUESTS,
    RATE_LIMIT_MESSAGE_REQUESTS,
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
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-ci-placeholder")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = bool_from_env("DJANGO_DEBUG", default=False)

AUTH_USER_MODEL = "accounts.User"

# Application definition
INSTALLED_APPS = [
    "daphne",
    "channels",
    "apps.accounts",
    "apps.billing",
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
    "apps.guards",
    "apps.chatlab",
    "apps.privacy",
    "apps.trainerlab",
    "apps.feedback",
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
                "apps.privacy.context_processors.privacy_flags",
                "apps.feedback.context_processors.staff_feedback_awareness",
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
            "NAME": os.getenv("POSTGRES_DB", "AppDatabase"),
            "USER": os.getenv("POSTGRES_USER", "appuser"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
            "HOST": os.getenv("POSTGRES_HOST", "db"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    raise ValueError(f"Unsupported database engine: {db_engine}")


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
ORCA_MAX_ATTEMPTS = int_from_env("ORCA_MAX_ATTEMPTS", default=4, minimum=1)
ORCA_RETRY_BACKOFF_BASE = int_from_env("ORCA_RETRY_BACKOFF_BASE", default=5, minimum=1)
ORCA_RETRY_BACKOFF_MAX = int_from_env("ORCA_RETRY_BACKOFF_MAX", default=60, minimum=1)
TRAINERLAB_RUNTIME_MAX_PROMPT_TOKENS = int_from_env(
    "TRAINERLAB_RUNTIME_MAX_PROMPT_TOKENS",
    default=7000,
    minimum=1000,
)
TRAINERLAB_RUNTIME_MAX_OUTPUT_TOKENS = optional_int_from_env(
    "TRAINERLAB_RUNTIME_MAX_OUTPUT_TOKENS",
    minimum=128,
)
TRAINERLAB_RUNTIME_MAX_BATCH_REASONS = int_from_env(
    "TRAINERLAB_RUNTIME_MAX_BATCH_REASONS",
    default=8,
    minimum=1,
)

# JWT Configuration (for mobile API clients)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "django-insecure-jwt-ci-placeholder")
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

SITE_NAME = check_env("SITE_NAME", default="MedSim")
SITE_ADMIN = {
    "NAME": check_env("SITE_ADMIN_NAME", default="MedSim"),
    "EMAIL": check_env("SITE_ADMIN_EMAIL", default="<admin@jackfruitco.com>"),
}

CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"
