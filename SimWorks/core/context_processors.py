# core/context_processors.py
from typing import Any

from django.conf import settings
from django.http import HttpRequest


def debug_flag(request):
    return {"debug": settings.DEBUG}

def site_info(request: HttpRequest) -> dict[str, Any]:
    """
    Adds site metadata to every template.

    Expects (in settings):
        SITE_NAME: str
        SITE_ADMIN: dict with keys NAME, EMAIL
    """
    site_admin_raw = getattr(settings, "SITE_ADMIN", {}) or {}
    site_admin = site_admin_raw if isinstance(site_admin_raw, dict) else {}

    return {
        "site": {
            "name": getattr(settings, "SITE_NAME", "SimWorks"),
            "admin": {
                "name": site_admin.get("NAME", "SimWorks"),
                "email": site_admin.get("EMAIL", ""),
            },
        },
    }