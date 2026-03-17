# SimWorks/apps/common/checks.py

from collections.abc import Callable

from django.conf import settings
from django.core.checks import Error, Tags, register


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


@register(Tags.security)
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
    if email_backend == "django.core.mail.backends.console.EmailBackend":
        errors.append(
            Error(
                "Console email backend is not suitable for production.",
                hint="Set EMAIL_BACKEND to a real backend "
                "(e.g. django.core.mail.backends.smtp.EmailBackend).",
                id="config.E011",
            )
        )

    return errors
