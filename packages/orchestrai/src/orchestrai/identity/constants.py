"""Canonical identity constants shared across the identity layer.

This module is retained for backward compatibility; new code should import
from ``orchestrai.identity.domains`` instead.
"""

from .domains import DEFAULT_DOMAIN, normalize_domain  # noqa: F401

__all__ = ["DEFAULT_DOMAIN", "normalize_domain"]
