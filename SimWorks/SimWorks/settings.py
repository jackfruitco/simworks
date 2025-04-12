import os
import os
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from core.utils import check_env
from .logging import LOGGING

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
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"

# Set Allowed Hosts
if (hosts := os.getenv("DJANGO_ALLOWED_HOSTS")) is not None:
    ALLOWED_HOSTS = [host for host in re.split(r"\s*,\s*", hosts.strip()) if host]
else:
    ALLOWED_HOSTS = []

# CSRF Configuration
if (origins := os.getenv("CSRF_TRUSTED_ORIGINS", None)) is not None:
    CSRF_TRUSTED_ORIGINS = [
        origin for origin in re.split(r"\s*,\s*", origins.strip()) if origin
    ]
else:
    CSRF_TRUSTED_ORIGINS = []

CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "true").lower() == "true"

AUTH_USER_MODEL = "accounts.CustomUser"

# Application definition
INSTALLED_APPS = [
    "daphne",
    "channels",
    "accounts",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "core",
    "ChatLab",
    "django_htmx",
]


MIDDLEWARE = [
    "core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "SimWorks.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "SimWorks.wsgi.application"
ASGI_APPLICATION = "SimWorks.asgi.application"


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases
# Database engine can be chosen via environment variable "DATABASE"
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

OPENAI_API_KEY = check_env("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", 'gpt-4o-mini')

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                f"redis://:{check_env('REDIS_PASSWORD')}@{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', 6379)}"
            ],
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators
AUTH_USER_MODEL = "accounts.CustomUser"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR.parent / "static"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Media files (uploaded by users)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR.parent / "media"

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SITE_NAME = check_env("SITE_NAME")
SITE_ADMIN = {
    "NAME": check_env("SITE_ADMIN_NAME", default="SimWorks"),
    "EMAIL": check_env("SITE_ADMIN_EMAIL", default="<EMAIL>"),
}
