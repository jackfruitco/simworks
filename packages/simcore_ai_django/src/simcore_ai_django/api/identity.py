"""
Stable import surface for SimWorks apps to access identity helpers.

This module provides a facade over identity utilities, respecting the import-boundary rule.
All identity-related helpers should be imported from this module by SimWorks Django apps.
"""

from simcore_ai.identity import Identity, IdentityMixin
from simcore_ai_django.identity.utils import *

__all__ = [
    "Identity",
    # Mixins
    "IdentityMixin",
    # Django-aware helpers
    "derive_django_identity_for_class",
    "get_app_label_for_class",
    "resolve_collision_django",
    # Re-exports from core for convenience
    "DEFAULT_STRIP_TOKENS",
    "snake",
    "strip_tokens",
    "derive_name_from_class",
    "module_root",
    "derive_identity_for_class",
    "resolve_collision",
    "parse_dot_identity",
]
