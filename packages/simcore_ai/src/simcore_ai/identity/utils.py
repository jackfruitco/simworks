# simcore_ai/identity/utils.py
"""
Core identity utilities for SimCore AI (framework-agnostic).

This module provides pure helpers used by the identity *resolver*:

- Name normalization (`snake`)
- Segment-aware token stripping for class names (`strip_tokens`)
- Module root extraction (`module_root`)
- Identity collision resolution (`resolve_collision`)
- Strict dot-identity parsing (`parse_dot_identity`)

Design:
- Pure-Python; no Django dependencies.
- Canonical identity uses the vocabulary `(namespace, kind, name)`.
- Canonical string form is dot-only: "namespace.kind.name".

Notes:
- *Derivation* of identities is handled by `simcore_ai.identity.resolution.IdentityResolver`.
  This module intentionally no longer exposes `derive_identity_for_class`.
"""



import logging
import os
import re
from collections.abc import Iterable, Callable
from typing import Optional, Union, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from . import IdentityLike, Identity

__all__ = [
    "DEFAULT_IDENTITY_STRIP_TOKENS",
    "strip_tokens",
    "snake",
    "module_root",
    "resolve_collision",
    "parse_dot_identity",
    "coerce_identity_key",
]

logger = logging.getLogger(__name__)

# Default tokens to strip from class names when deriving a *name*.
# These are *segments* (e.g., CamelCase parts or underscore/hyphen tokens).
DEFAULT_IDENTITY_STRIP_TOKENS: tuple[str, ...] = (
    "Codec",
    "Service",
    "Prompt",
    "PromptSection",
    "Section",
    "Response",
    "Generate",
    "Generation",
    "Output",
    "Schema",
    "Mixin",
)

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


# ---------------- segment-aware stripping ----------------

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[0-9a-z])([A-Z])")
_NON_ALNUM_SEP_RE = re.compile(r"[\W_\-]+")


def _split_segments(name: str) -> list[str]:
    """Split a class name into segments by CamelCase boundaries and `_`/`-`/non-alnum.

    Examples:
        "CodecStrippedResponse" -> ["Codec", "Stripped", "Response"]
        "Special_Response-Custom" -> ["Special", "Response", "Custom"]
    """
    if not name:
        return []
    # Put spaces before CamelCase transitions and replace separators with spaces
    s = _CAMEL_BOUNDARY_RE.sub(r" \1", name)
    s = re.sub(r"[\-_]+", " ", s)
    parts = [p for p in _NON_ALNUM_SEP_RE.split(s) if p]
    return parts


def _normalize_segments_to_name(segments: list[str], *, lower: bool = True) -> str:
    """Join segments with '-' and normalize repeated separators and edges."""
    if not segments:
        return ""
    s = "-".join(segments)
    s = re.sub(r"[._\s\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s.lower() if lower else s


def strip_tokens(name: str, extra_tokens: Iterable[str] = ()) -> str:
    """Segment-aware token stripping (case-insensitive, prefix/middle/suffix).

    - Splits the input into *segments* using CamelCase boundaries and `_`/`-`/non-alnum
    - Drops any segment that *fully matches* one of the tokens (case-insensitive)
    - Re-joins remaining segments with `-` (normalization will collapse further)

    This function is intended for **derived names only**. If a name was explicitly
    provided via decorator arg or class attribute, callers should *not* apply
    token stripping, only normalization.
    """
    if not name:
        return ""

    # Build the case-insensitive token set. Include default tokens first, then extras.
    token_set = {t.casefold() for t in DEFAULT_IDENTITY_STRIP_TOKENS}
    for t in (extra_tokens or ()):  # type: ignore[union-attr]
        if isinstance(t, str) and t:
            token_set.add(t.casefold())

    segs = _split_segments(name)
    if not segs:
        return name

    kept = [s for s in segs if s.casefold() not in token_set]
    # If everything was stripped, fall back to the original name (normalized in resolver)
    return _normalize_segments_to_name(kept, lower=False) if kept else ""


# ---------------- misc helpers ----------------

def module_root(cls_or_module: Union[str, type]) -> Optional[str]:
    """Return the root module name for a class or module string (first segment before a dot)."""
    if isinstance(cls_or_module, str):
        module_name = cls_or_module
    else:
        module_name = getattr(cls_or_module, "__module__", None)
        if module_name is None:
            return None
    return module_name.split(".", 1)[0] if module_name else None


def resolve_collision(
        kind: str,
        ident_tuple: tuple[str, str, str],
        *,
        debug: Optional[bool] = None,
        exists: Callable[[tuple[str, str, str]], bool],
) -> tuple[str, str, str]:
    """Resolve identity collisions.

    If `exists(ident_tuple)` is True:
      - In debug mode → raise RuntimeError.
      - In non-debug → append "-2", "-3", … to the **name** until unique.

    Args:
        kind: Human label for error/warn input ("codec", "service", "prompt", etc.).
        ident_tuple: (namespace, kind, name)
        debug: If None, falls back to SIMCORE_AI_DEBUG env var.
        exists: Callable that returns True if the identity already exists.
    """
    if debug is None:
        debug = _DEBUG_FALLBACK

    namespace, kind_part, name = ident_tuple
    if not exists(ident_tuple):
        return ident_tuple

    if debug:
        raise RuntimeError(f"Collision detected for {kind} identity {ident_tuple} (debug=True).")

    # Append name suffixes until unique
    suffix = 2
    while True:
        candidate = (namespace, kind_part, f"{name}-{suffix}")
        if not exists(candidate):
            logger.warning(
                "Collision detected for %s identity %s, renaming to %s.",
                kind, ".".join(ident_tuple), ".".join(candidate)
            )
            return candidate
        suffix += 1


def parse_dot_identity(key: str) -> tuple[str, str, str]:
    """Parse a dot-only identity string into (namespace, kind, name).

    Strict rules:
      - Exactly 3 non-empty components
      - Dot separator only (no colons)
      - Surrounding whitespace is ignored

    Raises:
        ValueError: if the string is not a valid dot identity.
    """
    key = key.strip()
    if ":" in key:
        raise ValueError(
            f"Invalid identity '{key}': colons are not allowed. Use 'namespace.kind.name' only."
        )
    parts = [p.strip() for p in key.split(".")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"Invalid identity '{key}': expected exactly three dot-separated parts."
        )
    return parts[0], parts[1], parts[2]


def coerce_identity_key(value: "IdentityLike") -> Optional[tuple[str, str, str]]:
    """Coerce (tuple | Identity | 'ns.kind.name' str) to a normalized (ns, kind, name) tuple.

    This is a thin compatibility wrapper around the centralized Identity API.
    It prefers `Identity.get_for(...)` when available and falls back to
    strict dot parsing. Returns ``None`` on failure rather than raising.
    """
    # Local import to avoid import cycles at module import time
    from .identity import Identity

    # Fast path: already a triple
    if isinstance(value, tuple) and len(value) == 3:
        ns, kd, nm = value  # type: ignore[misc]
        return str(ns), str(kd), str(nm)

    # Identity instance
    if isinstance(value, Identity):  # type: ignore[arg-type]
        return value.as_tuple3  # type: ignore[union-attr]

    # Dot-string → prefer Identity.get_for, else strict parser fallback
    if isinstance(value, str):
        try:
            if Identity is not None:
                ident = Identity.get_for(value)  # strict coercion; may raise
                return ident.as_tuple3
            # Fallback: strict parse to tuple3
            return parse_dot_identity(value)
        except Exception:
            return None

    # Last resort: if Identity API is available, attempt strict coercion
    if Identity is not None:
        try:
            ident = Identity.get_for(value)  # may raise for unsupported types
            return ident.as_tuple3
        except Exception:
            return None

    return None
