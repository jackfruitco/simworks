"""
Stable import surface for SimWorks apps to access identity helpers.

This module provides a facade over identity utilities, respecting the import-boundary rule.
All identity-related helpers should be imported from this module by SimWorks Django apps.
"""

from orchestrai.identity import Identity, IdentityMixin
from orchestrai_django.identity import DjangoIdentityMixin, DjangoIdentityResolver

__all__ = [
    # Mixins
    "Identity",
    "DjangoIdentityMixin",
    "DjangoIdentityResolver",
]
