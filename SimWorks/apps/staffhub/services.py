"""Service layer for the staff dashboard.

Builds the list of dashboard links (filtered by user permissions) and a
lightweight environment/status snapshot. No database models — links are
defined in code as ``StaffLink`` dataclass instances.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from django.conf import settings
from django.db import connection
from django.urls import NoReverseMatch, reverse

from apps.common.services.build_info import (
    get_backend_build_time,
    get_backend_commit,
    get_backend_version,
    get_orchestrai_version,
)


@dataclass(frozen=True)
class StaffLink:
    label: str
    url: str
    group: str
    description: str = ""
    superuser_only: bool = False
    external: bool = False


def maybe_reverse(name: str, *args, **kwargs) -> str | None:
    try:
        return reverse(name, *args, **kwargs)
    except NoReverseMatch:
        return None


def _add(links: list[StaffLink], url: str | None, **kwargs: Any) -> None:
    if url:
        links.append(StaffLink(url=url, **kwargs))


def get_staff_dashboard_links(user) -> list[StaffLink]:
    """Return dashboard links visible to ``user``.

    Filters ``superuser_only`` entries in Python before they reach the
    template — do not rely on template-only hiding.
    """
    links: list[StaffLink] = []

    # Admin
    _add(
        links,
        maybe_reverse("admin:index"),
        label="Django Admin",
        group="Admin",
        description="Manage Django models and system data.",
        superuser_only=True,
    )
    # Django Ninja exposes docs/openapi at well-known paths under /api/v1/.
    # Hardcoded because Ninja's URL names vary across versions; superuser-only.
    _add(
        links,
        "/api/v1/docs",
        label="API Docs",
        group="Admin",
        description="Interactive REST API documentation.",
        superuser_only=True,
    )
    _add(
        links,
        "/api/v1/openapi.json",
        label="OpenAPI Schema",
        group="Admin",
        description="Raw OpenAPI schema (JSON).",
        superuser_only=True,
    )

    # Simulations
    _add(
        links,
        maybe_reverse("chatlab:index"),
        label="ChatLab",
        group="Simulations",
        description="Patient chat simulations.",
    )
    _add(
        links,
        maybe_reverse("trainerlab:index"),
        label="TrainerLab",
        group="Simulations",
        description="Trainer-led simulation sessions.",
    )
    # TODO(staffhub): add a simulation list / failed-runs page when one exists.

    # AI / Prompts
    # TODO(staffhub): wire Prompt Library, Instruction Registry, Service
    # Registry, and Token Usage links when those internal pages exist.

    # Accounts / Billing
    _add(
        links,
        maybe_reverse("staff:user-list"),
        label="Users",
        group="Accounts",
        description="Browse and manage user accounts.",
        superuser_only=True,
    )
    _add(
        links,
        maybe_reverse("staff:account-list"),
        label="Accounts",
        group="Accounts",
        description="Browse organizational accounts.",
        superuser_only=True,
    )
    _add(
        links,
        maybe_reverse("staff:invitation-list"),
        label="Invitations",
        group="Accounts",
        description="Send and manage user invitations.",
        superuser_only=True,
    )
    _add(
        links,
        maybe_reverse("billing:home"),
        label="Billing",
        group="Accounts",
        description="Billing and subscription management.",
        superuser_only=True,
    )
    # TODO(staffhub): add Entitlements and Subscriptions when dedicated
    # internal pages exist.

    # Observability
    _add(
        links,
        "/api/v1/health",
        label="Health Check",
        group="Observability",
        description="API health endpoint.",
    )
    # TODO(staffhub): add Logs UI, SSE Events viewer, and Celery/Redis status
    # pages when those internal pages exist.

    # Feedback
    _add(
        links,
        maybe_reverse("feedback:staff-list"),
        label="Feedback Inbox",
        group="Feedback",
        description="User-submitted product feedback.",
    )

    # External Tools — settings-driven, optional, superuser-only.
    external_links = getattr(settings, "STAFFHUB_EXTERNAL_LINKS", {}) or {}
    for key, url in external_links.items():
        if not url:
            continue
        links.append(
            StaffLink(
                label=str(key).replace("_", " ").title(),
                url=str(url),
                group="External Tools",
                external=True,
                superuser_only=True,
            )
        )

    if not user.is_superuser:
        links = [link for link in links if not link.superuser_only]

    return links


def _check_database() -> str:
    try:
        connection.ensure_connection()
        return "connected"
    except Exception:
        return "unavailable"


def _check_redis() -> str:
    hostname = getattr(settings, "REDIS_HOSTNAME", None) or os.getenv("REDIS_HOSTNAME")
    if not hostname:
        return "unknown"
    try:
        import redis  # type: ignore[import-not-found]
    except ImportError:
        return "unknown"
    try:
        client = redis.Redis(
            host=hostname,
            port=int(getattr(settings, "REDIS_PORT", 6379) or 6379),
            password=getattr(settings, "REDIS_PASSWORD", None),
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
        )
        return "connected" if client.ping() else "unavailable"
    except Exception:
        return "unavailable"


def _short(value: str | None, length: int = 7) -> str | None:
    if not value:
        return value
    return value[:length]


def get_staff_dashboard_status() -> dict[str, Any]:
    """Lightweight environment/version/status snapshot for the banner.

    Falls back to ``None`` / ``"unknown"`` for missing values rather than
    raising, so the dashboard renders even in minimal configurations.
    """
    return {
        "environment": os.getenv("EMAIL_ENVIRONMENT_NAME") or "unknown",
        "version": get_backend_version(),
        "commit": get_backend_commit(),
        "commit_short": _short(get_backend_commit()),
        "build_time": get_backend_build_time(),
        "orchestrai_version": get_orchestrai_version(),
        "debug": bool(getattr(settings, "DEBUG", False)),
        "database": _check_database(),
        "redis": _check_redis(),
        "openai_configured": bool(
            getattr(settings, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
        ),
    }
