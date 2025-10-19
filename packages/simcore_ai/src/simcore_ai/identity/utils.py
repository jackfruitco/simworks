# simcore_ai/identity/utils.py
"""
Core identity utilities for SimCore AI.

This module provides framework-agnostic helpers and primitives used for identity derivation
across AI components. It includes:

- Name normalization (`snake`)
- Class-name token stripping (`strip_tokens`)
- Name derivation from class names (`derive_name_from_class`)
- Module root extraction (`module_root`)
- Identity derivation (`derive_identity_for_class`)
- Identity collision resolution (`resolve_collision`)
- Strict dot-identity parsing (`parse_dot_identity`)

Design:
- Pure-Python; no Django dependencies.
- Canonical identity is a tuple3: (origin, bucket, name).
- Canonical string form is dot-only: "origin.bucket.name".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable, Optional, Tuple, Callable, Union

__all__ = [
    "DEFAULT_STRIP_TOKENS",
    "snake",
    "strip_tokens",
    "derive_name_from_class",
    "module_root",
    "derive_identity_for_class",
    "resolve_collision",
    "parse_dot_identity",
]

logger = logging.getLogger(__name__)

# Default suffix tokens to strip from class names when deriving identity "name"
DEFAULT_STRIP_TOKENS = {
    "Codec", "Service", "Prompt", "PromptSection", "Section", "Response",
    "Generate", "Output", "Schema",
}


def _env_truthy(value: str | None) -> bool:
    """Return True if the string looks truthy ("1", "true", "yes", case-insensitive)."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


# If no debug flag is provided to `resolve_collision`, we fall back to this env var.
_DEBUG_FALLBACK = _env_truthy(os.getenv("SIMCORE_AI_DEBUG"))


def snake(s: str) -> str:
    """Convert CamelCase or mixedCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def strip_tokens(
    name: str,
    extra_tokens: Iterable[str] = (),
    *,
    strip_leading: bool = True,
    strip_trailing: bool = True,
    repeat: bool = True,
) -> str:
    """Remove provided tokens from the *edges* of a class name.

    - Strips tokens from the **leading** and/or **trailing** edge(s) (configurable).
    - If `repeat=True` (default), keeps stripping while any token still matches either edge.
    - Longest tokens are tried first to avoid partial overlaps.
    - Trims leftover underscores/spaces/hyphens at the edges.

    Notes:
        • Matching is case-sensitive. Provide the exact-cased tokens you expect
          (Django utils already adds app-label variants).
        • Only edges are stripped — interior occurrences are preserved.
    """
    tokens = list(DEFAULT_STRIP_TOKENS) + list(extra_tokens)
    # Try longest first to avoid partial matches swallowing each other.
    tokens.sort(key=len, reverse=True)

    out = name or ""
    if not out or (not strip_leading and not strip_trailing):
        return name

    def _strip_once(s: str) -> tuple[str, bool]:
        changed = False
        for tok in tokens:
            if strip_leading and s.startswith(tok):
                s = s[len(tok):]
                changed = True
            if strip_trailing and s.endswith(tok):
                s = s[:-len(tok)]
                changed = True
        return s, changed

    if repeat:
        while True:
            out, changed = _strip_once(out)
            if not changed:
                break
    else:
        out, _ = _strip_once(out)

    # Clean padding artifacts produced by token removal.
    out = out.strip("_- ").strip()
    # Guard: if we stripped everything, fall back to the original name.
    return out or name


def derive_name_from_class(cls_name: str, extra_tokens: Iterable[str] = ()) -> str:
    """Derive a normalized name from a class name by stripping common suffix tokens then snake-casing."""
    return snake(strip_tokens(cls_name, extra_tokens))


def module_root(cls_or_module: Union[str, type]) -> Optional[str]:
    """Return the root module name for a class or module string (first segment before a dot)."""
    if isinstance(cls_or_module, str):
        module_name = cls_or_module
    else:
        module_name = getattr(cls_or_module, "__module__", None)
        if module_name is None:
            return None
    return module_name.split(".", 1)[0] if module_name else None


def derive_identity_for_class(
        cls: type,
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
        strip_tokens: Iterable[str] = (),
) -> Tuple[str, str, str]:
    """Derive a tuple identity (origin, bucket, name) for a class.

    Rules:
      - origin: explicit → module_root(cls) → "default"
      - bucket: explicit → "default"
      - name:   explicit → strip suffix tokens from class name → snake_case

    All three parts are normalized via `snake()` before returning.
    """
    o_raw = origin or module_root(cls) or "default"
    b_raw = bucket or "default"
    if name is not None:
        n_raw = name
    else:
        cls_name = getattr(cls, "__name__", str(cls))
        n_raw = derive_name_from_class(cls_name, strip_tokens)

    return snake(o_raw), snake(b_raw), snake(n_raw)


def resolve_collision(
        kind: str,
        ident_tuple: Tuple[str, str, str],
        *,
        debug: Optional[bool] = None,
        exists: Callable[[Tuple[str, str, str]], bool],
) -> Tuple[str, str, str]:
    """Resolve identity collisions.

    If `exists(ident_tuple)` is True:
      - In debug mode → raise RuntimeError.
      - In non-debug → append "-2", "-3", … to the name until unique.

    Args:
        kind: Human label for error/warn messages ("codec", "service", "prompt", etc.).
        ident_tuple: (origin, bucket, name)
        debug: If None, falls back to SIMCORE_AI_DEBUG env var.
        exists: Callable that returns True if the identity already exists.
    """
    if debug is None:
        debug = _DEBUG_FALLBACK

    origin, bucket, name = ident_tuple
    if not exists(ident_tuple):
        return ident_tuple

    if debug:
        raise RuntimeError(f"Collision detected for {kind} identity {ident_tuple} (debug=True).")

    # Append name suffixes until unique
    suffix = 2
    while True:
        candidate = (origin, bucket, f"{name}-{suffix}")
        if not exists(candidate):
            logger.warning(
                "Collision detected for %s identity %s, renaming to %s.",
                kind, ".".join(ident_tuple), ".".join(candidate)
            )
            return candidate
        suffix += 1


def parse_dot_identity(key: str) -> Tuple[str, str, str]:
    """Parse a dot-only identity string into (origin, bucket, name).

    Strict rules:
      - Exactly 3 non-empty components
      - Dot separator only (no colons)
      - Surrounding whitespace is ignored

    Raises:
        ValueError: if the string is not a valid dot identity.
    """
    if ":" in key:
        raise ValueError(f"Invalid identity '{key}': colons are not allowed. Use 'origin.bucket.name' only.")
    parts = [p.strip() for p in key.split(".")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"Invalid identity '{key}': expected exactly three dot-separated parts.")
    return parts[0], parts[1], parts[2]
