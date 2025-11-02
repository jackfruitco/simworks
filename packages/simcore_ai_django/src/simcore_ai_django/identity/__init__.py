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

from .mixins import DjangoIdentityMixin
from .resolvers import DjangoIdentityResolver
from .utils import APP_IDENTITY_STRIP_TOKENS, get_app_identity_strip_tokens, infer_namespace_from_module

__all__ = [
    "DjangoIdentityMixin",
    "DjangoIdentityResolver",
    "APP_IDENTITY_STRIP_TOKENS",
    "get_app_identity_strip_tokens",
    "infer_namespace_from_module"
]
