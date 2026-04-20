# SimWorks/apps/common/checks.py

from __future__ import annotations

from collections.abc import Callable
from email.utils import parseaddr
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

POSTMARK_BACKEND = "anymail.backends.postmark.EmailBackend"
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
APPROVED_EMAIL_HOSTS = {"medsim.jackfruitco.com", "medsim-staging.jackfruitco.com"}


def _missing_setting(name: str) -> bool:
    value = getattr(settings, name, None)
    return value is None or (isinstance(value, str) and value.strip() == "")


def _prod_only() -> bool:
    return not settings.DEBUG


def _redis_enabled() -> bool:
    return bool(getattr(settings, "REDIS_ENABLED", False))


def _smtp_enabled() -> bool:
    return getattr(settings, "EMAIL_BACKEND", "") == "django.core.mail.backends.smtp.EmailBackend"


# condition, setting name, error id, message, hint
# Use resolved Django setting names for all checks.
DEPLOY_SETTING_CHECKS: list[tuple[Callable[[], bool], str, str, str, str]] = [
    (
        _prod_only,
        "SECRET_KEY",
        "config.E001",
        "SECRET_KEY is missing.",
        "Set the `SECRET_KEY` environment variable.",
    ),
    (
        _prod_only,
        "POSTGRES_PASSWORD",
        "config.E002",
        "POSTGRES_PASSWORD is missing.",
        "Set the `POSTGRES_PASSWORD` environment variable.",
    ),
    (
        _prod_only,
        "LOGFIRE_API_KEY",
        "config.E003",
        "LOGFIRE_API_KEY is missing.",
        "Set the `LOGFIRE_API_KEY` environment variable.",
    ),
    (
        _prod_only,
        "JWT_SECRET_KEY",
        "config.E004",
        "JWT_SECRET_KEY is missing.",
        "Set the `JWT_SECRET_KEY` environment variable.",
    ),
]


FEATURE_SETTING_CHECKS: list[tuple[Callable[[], bool], str, str, str, str]] = [
    (
        _smtp_enabled,
        "EMAIL_HOST_PASSWORD",
        "config.E006",
        "EMAIL_HOST_PASSWORD is missing while SMTP email backend is enabled.",
        "Set EMAIL_HOST_PASSWORD or use a different email backend.",
    ),
    (
        _prod_only,
        "REDIS_PASSWORD",
        "config.E005",
        "REDIS_PASSWORD is missing.",
        "Set the `REDIS_PASSWORD` environment variable.",
    ),
]


def _is_valid_email_identity(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    _, address = parseaddr(value)
    return bool(address and "@" in address)


@register(Tags.security, deploy=True)
def check_required_env_vars(app_configs, **kwargs):
    errors = []

    setting_checks = [*DEPLOY_SETTING_CHECKS, *FEATURE_SETTING_CHECKS]

    for condition, setting_name, error_id, message, hint in setting_checks:
        if condition() and _missing_setting(setting_name):
            errors.append(
                Error(
                    message,
                    hint=hint,
                    id=error_id,
                )
            )

    return errors


@register(Tags.security, deploy=True)
def check_production_settings(app_configs, **kwargs):
    """Validate production-unsafe settings when DEBUG=False."""
    errors = []

    if not _prod_only():
        return errors

    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        errors.append(
            Error(
                "CORS_ALLOW_ALL_ORIGINS must not be True in production.",
                hint="Set DJANGO_CORS_ALLOW_ALL_ORIGINS=false or remove the variable.",
                id="config.E010",
            )
        )

    email_backend = getattr(settings, "EMAIL_BACKEND", "")
    if email_backend == CONSOLE_BACKEND:
        errors.append(
            Error(
                "Console email backend is not suitable for production.",
                hint="Set EMAIL_BACKEND to Anymail Postmark backend in staging/production.",
                id="config.E011",
            )
        )

    secret_key = getattr(settings, "SECRET_KEY", "")
    if isinstance(secret_key, str) and secret_key.startswith("django-insecure-"):
        errors.append(
            Error(
                "SECRET_KEY is using an insecure placeholder value.",
                hint="Set the DJANGO_SECRET_KEY environment variable to a secure random value.",
                id="config.E012",
            )
        )

    jwt_key = getattr(settings, "JWT_SECRET_KEY", "")
    if isinstance(jwt_key, str) and jwt_key.startswith("django-insecure-"):
        errors.append(
            Error(
                "JWT_SECRET_KEY is using an insecure placeholder value.",
                hint="Set the JWT_SECRET_KEY environment variable to a secure random value.",
                id="config.E013",
            )
        )

    return errors


@register(Tags.security, deploy=True)
def check_email_configuration(app_configs, **kwargs):
    errors = []
    warnings = []

    email_backend = getattr(settings, "EMAIL_BACKEND", "")

    if _prod_only() and email_backend == CONSOLE_BACKEND:
        errors.append(
            Error(
                "EMAIL_BACKEND uses console backend while DEBUG=False.",
                hint="Set EMAIL_BACKEND=anymail.backends.postmark.EmailBackend.",
                id="config.E014",
            )
        )

    if email_backend == POSTMARK_BACKEND and _missing_setting("POSTMARK_SERVER_TOKEN"):
        errors.append(
            Error(
                "POSTMARK_SERVER_TOKEN is required when using Postmark backend.",
                hint="Set POSTMARK_SERVER_TOKEN in the runtime environment.",
                id="config.E015",
            )
        )

    for setting_name, error_id in (
        ("DEFAULT_FROM_EMAIL", "config.E016"),
        ("EMAIL_REPLY_TO", "config.E017"),
        ("SERVER_EMAIL", "config.E018"),
    ):
        value = getattr(settings, setting_name, "")
        if not _is_valid_email_identity(value):
            errors.append(
                Error(
                    f"{setting_name} is empty or not a valid email identity.",
                    hint=f"Set {setting_name} to a valid address (or display-name format).",
                    id=error_id,
                )
            )

    email_base_url = getattr(settings, "EMAIL_BASE_URL", "")
    parsed = urlparse(email_base_url)
    if not parsed.hostname:
        errors.append(
            Error(
                "EMAIL_BASE_URL is missing a valid host.",
                hint="Set EMAIL_BASE_URL to an absolute https URL for MedSim app host.",
                id="config.E019",
            )
        )
    elif parsed.hostname not in APPROVED_EMAIL_HOSTS:
        warnings.append(
            Warning(
                "EMAIL_BASE_URL host is not one of the approved MedSim hosts.",
                hint=(
                    "Expected medsim.jackfruitco.com or medsim-staging.jackfruitco.com; "
                    "verify this deployment intentionally uses a custom host."
                ),
                id="config.W001",
            )
        )

    return [*errors, *warnings]
