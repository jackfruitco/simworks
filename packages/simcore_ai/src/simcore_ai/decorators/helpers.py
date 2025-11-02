# simcore_ai/decorators/helpers.py
"""
Lightweight, framework-agnostic helpers for decorators.

⚠️ Deprecation note
-------------------
All *identity derivation* logic has moved to
`simcore_ai.identity.resolution.IdentityResolver`.
This module now delegates identity validation to the centralized Identity class and prefers core utils for name transforms.
"""

from __future__ import annotations

import re
import warnings
from typing import Iterable

from simcore_ai.identity import Identity
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
    """Convert CamelCase / PascalCase to snake_case using core utility.

    Kept for legacy call sites; prefer `snake()` from `simcore_ai.identity.utils`.
    """
    from simcore_ai.identity.utils import snake as _snake  # local import to avoid legacy cycles
    if not name:
        return ""
    return _snake(name)


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
    warnings.warn(
        "validate_identity() is deprecated; use Identity.validate(namespace, kind, name) "
        "or construct Identity(...) directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    Identity.validate(namespace, kind, name)
