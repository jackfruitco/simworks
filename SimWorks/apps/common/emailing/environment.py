"""Deterministic environment helpers for transactional email rendering."""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest

PRODUCTION_HOST = "medsim.jackfruitco.com"
STAGING_HOST = "medsim-staging.jackfruitco.com"
PRODUCTION_BASE_URL = f"https://{PRODUCTION_HOST}"
STAGING_BASE_URL = f"https://{STAGING_HOST}"


def _normalize_host(host: str | None) -> str:
    if not host:
        return ""
    return host.split(":", 1)[0].strip().lower()


def _normalize_hint(environment_hint: str | None) -> str | None:
    if not environment_hint:
        return None
    hint = environment_hint.strip().lower()
    if hint in {"staging", "production"}:
        return hint
    return None


def _request_environment_label(request: HttpRequest | None) -> str | None:
    if request is None:
        return None

    try:
        host = _normalize_host(request.get_host())
    except DisallowedHost:
        host = _normalize_host(request.META.get("HTTP_HOST"))
    if host == STAGING_HOST:
        return "staging"
    if host == PRODUCTION_HOST:
        return "production"
    return None


def _settings_environment_label() -> str:
    env_name = str(getattr(settings, "EMAIL_ENVIRONMENT_NAME", "")).strip().lower()
    return "staging" if env_name == "staging" else "production"


def _configured_base_url_for_environment(environment_label: str) -> str | None:
    configured_base_url = str(getattr(settings, "EMAIL_BASE_URL", "")).strip().rstrip("/")
    if not configured_base_url:
        return None

    configured_host = _normalize_host(urlparse(configured_base_url).hostname)
    if not configured_host:
        return None

    if configured_host == STAGING_HOST:
        return configured_base_url if environment_label == "staging" else None
    if configured_host == PRODUCTION_HOST:
        return configured_base_url if environment_label == "production" else None

    settings_label = _settings_environment_label()
    if environment_label == settings_label:
        return configured_base_url
    return None


def get_email_environment_label(
    request: HttpRequest | None = None,
    environment_hint: str | None = None,
) -> str:
    normalized_hint = _normalize_hint(environment_hint)
    if normalized_hint:
        return normalized_hint

    request_label = _request_environment_label(request)
    if request_label:
        return request_label

    return _settings_environment_label()


def is_staging_email_context(
    request: HttpRequest | None = None,
    environment_hint: str | None = None,
) -> bool:
    return get_email_environment_label(request=request, environment_hint=environment_hint) == "staging"


def get_email_base_url(
    request: HttpRequest | None = None,
    environment_hint: str | None = None,
) -> str:
    environment_label = get_email_environment_label(request=request, environment_hint=environment_hint)
    configured_base_url = _configured_base_url_for_environment(environment_label)
    if configured_base_url:
        return configured_base_url

    if environment_label == "staging":
        return STAGING_BASE_URL
    return PRODUCTION_BASE_URL
