"""Email and transactional messaging settings.

Temporary backend choice: iCloud SMTP for low-volume/private beta.
Keep this module provider-replaceable so switching to Postmark later is mostly
an EMAIL_BACKEND/settings change rather than app-code changes.
"""

from __future__ import annotations

import os

from .settings_parsers import bool_from_env

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
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
    CONSOLE_BACKEND if EMAIL_USE_CONSOLE_BACKEND else SMTP_BACKEND,
)

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.mail.me.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = bool_from_env("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = bool_from_env("EMAIL_USE_SSL", default=False)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

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

SMTP_CREDENTIALS_CONFIGURED = bool(EMAIL_HOST_USER and EMAIL_HOST_PASSWORD)
REQUIRES_SMTP_CREDENTIALS = EMAIL_BACKEND == SMTP_BACKEND and not _is_local_environment
