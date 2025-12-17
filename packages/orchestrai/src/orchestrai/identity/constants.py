"""Canonical identity constants shared across the identity layer."""

import re
from typing import Optional

__all__ = ["DEFAULT_DOMAIN", "normalize_domain"]

DEFAULT_DOMAIN = "default"


def normalize_domain(value: Optional[str], *, default: str | None = DEFAULT_DOMAIN) -> str:
    """Normalize a domain value, applying a canonical default when missing.

    Normalization collapses dots/underscores/hyphens/spaces into single hyphens,
    lowercases the result, and trims edges. A ``ValueError`` is raised if no
    usable value is provided and no ``default`` is supplied.
    """
    candidate = value if value is not None else default
    if candidate is None:
        raise ValueError("domain is required")
    if not isinstance(candidate, str):
        raise TypeError(f"domain must be a string (got {type(candidate)!r})")

    normalized = re.sub(r"[._\\s\-]+", "-", candidate.strip())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-").lower()
    if not normalized:
        if default is None:
            raise ValueError("domain cannot be empty")
        return normalize_domain(default, default=None)
    return normalized
