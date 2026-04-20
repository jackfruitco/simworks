"""Email and transactional messaging settings."""

from __future__ import annotations

import os

from .settings_parsers import bool_from_env

POSTMARK_BACKEND = "anymail.backends.postmark.EmailBackend"
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_ENVIRONMENT_NAME = os.getenv(
    "EMAIL_ENVIRONMENT_NAME",
    "local" if bool_from_env("DJANGO_DEBUG", default=False) else "production",
).strip().lower()

_LOCAL_ENVIRONMENTS = {"local", "development", "dev", "test"}
_is_local_environment = EMAIL_ENVIRONMENT_NAME in _LOCAL_ENVIRONMENTS

EMAIL_USE_CONSOLE_BACKEND = bool_from_env(
    "EMAIL_USE_CONSOLE_BACKEND",
    default=_is_local_environment,
)
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    CONSOLE_BACKEND if EMAIL_USE_CONSOLE_BACKEND else POSTMARK_BACKEND,
)

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "MedSim by Jackfruit <noreply@jackfruitco.com>",
)
EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", "support@jackfruitco.com")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", "errors@jackfruitco.com")
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "")
EMAIL_STAGING_SUBJECT_PREFIX = os.getenv("EMAIL_STAGING_SUBJECT_PREFIX", "[STAGING]")
EMAIL_STAGING_BANNER_ENABLED = bool_from_env(
    "EMAIL_STAGING_BANNER_ENABLED",
    default=EMAIL_ENVIRONMENT_NAME == "staging",
)

ACCOUNT_DEFAULT_HTTP_PROTOCOL = os.getenv("ACCOUNT_DEFAULT_HTTP_PROTOCOL", "https")

_default_email_base_url = "https://medsim-staging.jackfruitco.com"
if EMAIL_ENVIRONMENT_NAME != "staging":
    _default_email_base_url = "https://medsim.jackfruitco.com"
EMAIL_BASE_URL = os.getenv("EMAIL_BASE_URL", _default_email_base_url).rstrip("/")

POSTMARK_SERVER_TOKEN = os.getenv("POSTMARK_SERVER_TOKEN", "")
POSTMARK_MESSAGE_STREAM = os.getenv("POSTMARK_MESSAGE_STREAM", "")

ANYMAIL: dict[str, object] = {}
if POSTMARK_SERVER_TOKEN:
    ANYMAIL["POSTMARK_SERVER_TOKEN"] = POSTMARK_SERVER_TOKEN
if POSTMARK_MESSAGE_STREAM:
    ANYMAIL["POSTMARK_SEND_DEFAULTS"] = {"message_stream": POSTMARK_MESSAGE_STREAM}

_requires_postmark_token = EMAIL_BACKEND == POSTMARK_BACKEND and not _is_local_environment
if _requires_postmark_token and not POSTMARK_SERVER_TOKEN:
    raise ValueError(
        "POSTMARK_SERVER_TOKEN is required when EMAIL_BACKEND uses Postmark outside local/dev."
    )
