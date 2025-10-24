# simcore_ai_django/identity/__init__.py
"""
Django identity integration helpers.

This module provides a simple, import-safe surface for app-contributed
identity strip tokens that augment the core decorator behavior.

AppConfig will populate `APP_IDENTITY_STRIP_TOKENS` during startup
(`SimcoreAIDjangoConfig.ready()`), and the Django decorator mixins
consume them via `get_app_identity_strip_tokens()`.

Notes
-----
- This module must remain lightweight and safe at import-time.
- No Django imports here; `apps.py` writes into this module.
"""

from __future__ import annotations

# Populated at runtime by `simcore_ai_django.apps.SimcoreAIDjangoConfig.ready()`
APP_IDENTITY_STRIP_TOKENS: tuple[str, ...] = ()


def get_app_identity_strip_tokens() -> tuple[str, ...]:
    """
    Return the app-contributed identity strip tokens as a tuple of strings.

    The return type is stable (always a tuple); callers should not mutate it.
    """
    # Ensure we always return a tuple even if someone set it to None or other
    value = APP_IDENTITY_STRIP_TOKENS or ()
    return tuple(value)


__all__ = [
    "APP_IDENTITY_STRIP_TOKENS",
    "get_app_identity_strip_tokens",
]
