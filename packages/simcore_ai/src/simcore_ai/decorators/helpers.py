# packages/simcore_ai/src/simcore_ai/decorators/helpers.py
"""
Lightweight, framework-agnostic helpers for decorators.

⚠️ Deprecation note
-------------------
All *identity derivation* logic has moved to
`simcore_ai.identity.resolution.IdentityResolver`.

This module intentionally contains only small string utilities that some
call sites may still import. New code should rely on the resolver and on
`simcore_ai.identity.utils` for low-level helpers.
"""
from __future__ import annotations

import re
from typing import Iterable

from simcore_ai.identity.exceptions import IdentityError
from simcore_ai.identity.utils import strip_tokens as _strip_tokens  # segment-aware

__all__ = [
    "camel_to_snake",
    "normalize_name",
    "strip_name_tokens",
    "validate_identity",
]

# Separator pattern for collapsing and normalization
_SEP_RE = re.compile(r"[._\-\s]+")


def camel_to_snake(name: str) -> str:
    """Convert CamelCase / PascalCase to snake_case-ish (underscored).

    This is kept for a few legacy call sites; most callers should prefer
    `snake()` from `simcore_ai.identity.utils`.
    """
    if not name:
        return ""
    s = re.sub(r"(?<=[0-9a-z])([A-Z])", r"_\1", name)
    s = re.sub(r"__+", "_", s)
    return s


def normalize_name(name: str) -> str:
    """Normalize a display name:
      - collapse runs of separators to single '-'
      - trim leading/trailing separators/spaces
    Explicit names may include uppercase; this function does not force case.
    """
    if name is None:
        return ""
    s = _SEP_RE.sub("-", str(name))
    s = s.strip(" -._")
    s = re.sub(r"-{2,}", "-", s)
    return s


def strip_name_tokens(name: str, tokens: Iterable[str]) -> str:
    """Compatibility wrapper that uses the *segment-aware* `strip_tokens`.

    - Case-insensitive, segment-aware (prefix/middle/suffix)
    - Removes any *full-segment* that matches a token
    - Returns hyphen-joined segments (final normalization is typically applied by callers)
    """
    return _strip_tokens(name, tokens)


def validate_identity(namespace: str, kind: str, name: str) -> None:
    """Basic structural validation of identity parts.

    - Non-empty strings
    - Allowed characters: A–Z, a–z, 0–9, '.', '_', '-'
    - Max length 128
    """
    allowed = re.compile(r"^[A-Za-z0-9._-]+$")
    for label, value in (("namespace", namespace), ("kind", kind), ("name", name)):
        if not isinstance(value, str):
            raise IdentityError(f"{label} must be a string (got {type(value)!r})")
        v = value.strip()
        if not v:
            raise IdentityError(f"{label} cannot be empty")
        if len(v) > 128:
            raise IdentityError(f"{label} too long (>128)")
        if not allowed.match(v):
            raise IdentityError(f"{label} contains illegal characters: {value!r}")
