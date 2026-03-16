# SimWorks/apps/common/checks.py

from collections.abc import Callable
import os

from django.conf import settings
from django.core.checks import Error, Tags, register


def _missing(name: str) -> bool:
    value = os.getenv(name)
    return value is None or value.strip() == ""


def _prod_only() -> bool:
    return not settings.DEBUG


def _redis_enabled() -> bool:
    return bool(getattr(settings, "REDIS_ENABLED", False))


def _smtp_enabled() -> bool:
    return getattr(settings, "EMAIL_BACKEND", "") == "django.core.mail.backends.smtp.EmailBackend"


# condition, env var, error id, message, hint
ENV_CHECKS: list[tuple[Callable[[], bool], str, str, str, str]] = [
    (
        _prod_only,
        "DJANGO_SECRET_KEY",
        "config.E001",
        "DJANGO_SECRET_KEY is missing.",
        "Set DJANGO_SECRET_KEY in the environment for non-debug deployments.",
    ),
    (
        _prod_only,
        "POSTGRES_PASSWORD",
        "config.E002",
        "POSTGRES_PASSWORD is missing.",
        "Set POSTGRES_PASSWORD in the environment for non-debug deployments.",
    ),
    (
        _prod_only,
        "LOGFIRE_API_KEY",
        "config.E003",
        "LOGFIRE_API_KEY is missing.",
        "Set LOGFIRE_API_KEY in the environment for non-debug deployments.",
    ),
    (
        _prod_only,
        "JWT_SECRET_KEY",
        "config.E004",
        "JWT_SECRET_KEY is missing.",
        "Set JWT_SECRET_KEY in the environment for non-debug deployments.",
    ),
    (
        _redis_enabled,
        "REDIS_PASSWORD",
        "config.E005",
        "REDIS_PASSWORD is missing while Redis is enabled.",
        "Set REDIS_PASSWORD or disable Redis for this environment.",
    ),
    (
        _smtp_enabled,
        "EMAIL_HOST_PASSWORD",
        "config.E006",
        "EMAIL_HOST_PASSWORD is missing while SMTP email backend is enabled.",
        "Set EMAIL_HOST_PASSWORD or use a different email backend.",
    ),
]


@register(Tags.security)
def check_required_env_vars(app_configs, **kwargs):
    errors = []

    for condition, env_name, error_id, message, hint in ENV_CHECKS:
        if condition() and _missing(env_name):
            errors.append(
                Error(
                    message,
                    hint=hint,
                    id=error_id,
                )
            )

    return errors
