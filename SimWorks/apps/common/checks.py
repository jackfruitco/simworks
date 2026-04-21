# SimWorks/apps/common/checks.py

from __future__ import annotations

from collections.abc import Callable
from email.utils import parseaddr
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
APPROVED_EMAIL_HOSTS = {"medsim.jackfruitco.com", "medsim-staging.jackfruitco.com"}
_LOCAL_ENVIRONMENTS = {"local", "development", "dev", "test"}


def _missing_setting(name: str) -> bool:
    value = getattr(settings, name, None)
    return value is None or (isinstance(value, str) and value.strip() == "")


def _prod_only() -> bool:
    return not settings.DEBUG


def _smtp_enabled() -> bool:
    return getattr(settings, "EMAIL_BACKEND", "") == SMTP_BACKEND


def _is_non_dev_environment() -> bool:
    environment = str(getattr(settings, "EMAIL_ENVIRONMENT_NAME", "")).strip().lower()
    return environment not in _LOCAL_ENVIRONMENTS


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
        "EMAIL_HOST_USER",
        "config.E006",
        "EMAIL_HOST_USER is missing while SMTP email backend is enabled.",
        "Set EMAIL_HOST_USER to `apikey` for SendGrid SMTP.",
    ),
    (
        _smtp_enabled,
        "EMAIL_HOST_PASSWORD",
        "config.E007",
        "EMAIL_HOST_PASSWORD is missing while SMTP email backend is enabled.",
        "Set EMAIL_HOST_PASSWORD to the SendGrid API key.",
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
            errors.append(Error(message, hint=hint, id=error_id))

    return errors


@register(Tags.security, deploy=True)
def check_production_settings(app_configs, **kwargs):
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

    if getattr(settings, "EMAIL_BACKEND", "") == CONSOLE_BACKEND:
        errors.append(
            Error(
                "Console email backend is not suitable for production.",
                hint="Set EMAIL_BACKEND to django.core.mail.backends.smtp.EmailBackend.",
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

    if _is_non_dev_environment() and email_backend == CONSOLE_BACKEND:
        errors.append(
            Error(
                "EMAIL_BACKEND uses console backend in a non-dev email environment.",
                hint="Use SMTP backend for staging/production.",
                id="config.E014",
            )
        )

    if email_backend == SMTP_BACKEND:
        if _missing_setting("EMAIL_HOST_USER"):
            errors.append(
                Error(
                    "EMAIL_HOST_USER is required when SMTP backend is active.",
                    hint="Set EMAIL_HOST_USER to `apikey` for SendGrid SMTP.",
                    id="config.E015",
                )
            )
        if _missing_setting("EMAIL_HOST_PASSWORD"):
            errors.append(
                Error(
                    "EMAIL_HOST_PASSWORD is required when SMTP backend is active.",
                    hint="Set EMAIL_HOST_PASSWORD to the SendGrid API key.",
                    id="config.E020",
                )
            )
        email_host = str(getattr(settings, "EMAIL_HOST", "")).strip().lower()
        email_host_user = str(getattr(settings, "EMAIL_HOST_USER", "")).strip()
        if email_host == "smtp.sendgrid.net" and email_host_user and email_host_user != "apikey":
            warnings.append(
                Warning(
                    "EMAIL_HOST_USER is not the expected SendGrid SMTP username.",
                    hint="SendGrid SMTP generally requires EMAIL_HOST_USER=apikey.",
                    id="config.W002",
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
