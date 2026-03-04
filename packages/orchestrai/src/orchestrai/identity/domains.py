"""Identity domain constants and normalization helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import re

__all__ = [
    "CODECS_DOMAIN",
    "DEFAULT_DOMAIN",
    "PERSIST_DOMAIN",
    "PROMPT_SECTIONS_DOMAIN",
    "SCHEMAS_DOMAIN",
    "SERVICES_DOMAIN",
    "SUPPORTED_DOMAINS",
    "normalize_domain",
]

SERVICES_DOMAIN = "services"
CODECS_DOMAIN = "codecs"
PROMPT_SECTIONS_DOMAIN = "prompt-sections"
SCHEMAS_DOMAIN = "schemas"
PERSIST_DOMAIN = "persist"

# Canonical defaults & supported set
DEFAULT_DOMAIN = SERVICES_DOMAIN
SUPPORTED_DOMAINS: tuple[str, ...] = (
    SERVICES_DOMAIN,
    CODECS_DOMAIN,
    PROMPT_SECTIONS_DOMAIN,
    SCHEMAS_DOMAIN,
    PERSIST_DOMAIN,
)


def _normalize(value: str) -> str:
    normalized = re.sub(r"[._\s\-]+", "-", value.strip())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-").lower()
    if not normalized:
        raise ValueError("domain cannot be empty")
    return normalized


def normalize_domain(
    value: str | None,
    *,
    default: str | None = DEFAULT_DOMAIN,
    allowed: Sequence[str] | None = SUPPORTED_DOMAINS,
    extras: Iterable[str] | None = None,
) -> str:
    """Normalize a domain value and enforce membership in the supported set."""
    candidate = value if value is not None else default
    if candidate is None:
        raise ValueError("domain is required")
    if not isinstance(candidate, str):
        raise TypeError(f"domain must be a string (got {type(candidate)!r})")

    normalized = _normalize(candidate)
    if allowed is not None or extras:
        allowed_norm = {_normalize(v) for v in (allowed or ())}
        allowed_norm.update({_normalize(v) for v in (extras or ())})
        if normalized not in allowed_norm:
            supported = ", ".join(sorted(allowed_norm))
            raise ValueError(f"unsupported domain {candidate!r}; supported domains: {supported}")

    return normalized
