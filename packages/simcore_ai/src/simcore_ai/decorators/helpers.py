# packages/simcore_ai/src/simcore_ai/decorators/helpers.py
from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple, Type

from simcore_ai.identity.base import Identity
from simcore_ai.identity.exceptions import IdentityError

# Suffixes removed when deriving a name from a class name
_DERIVE_SUFFIXES: Tuple[str, ...] = ("Codec", "Service", "Section", "Schema")

# Allowed characters for identity parts (explicit names may include uppercase; we accept both)
_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Separator pattern for collapsing and segmentization
_SEP_RE = re.compile(r"[._-]+")


def camel_to_snake(name: str) -> str:
    """Convert CamelCase / PascalCase to snake-ish with underscores (then normalized later)."""
    # Insert underscore between a lower/number and Upper
    s = re.sub(r"(?<=[0-9a-z])([A-Z])", r"_\1", name)
    # Collapse multiple underscores
    s = re.sub(r"__+", "_", s)
    return s


def derive_name(
        cls: Type,
        *,
        name_arg: Optional[str],
        name_attr: Optional[str],
        derived_lower: bool = True,
) -> str:
    """
    Derive the `name` part.

    Rules:
    - If an explicit name is provided (decorator arg or class attribute), use it *as-is* (whitespace trimmed).
      No token stripping or case normalization is applied to explicit names.
    - Otherwise, derive from class name:
        * strip one of: Codec|Service|Section|Schema (if present, once)
        * CamelCase -> snake-ish
        * lower() (controlled by `derived_lower`, default True)
    """
    if name_arg is not None and str(name_arg).strip():
        return str(name_arg).strip()

    if name_attr is not None and str(name_attr).strip():
        return str(name_attr).strip()

    cls_name = getattr(cls, "__name__", "") or ""
    base = cls_name
    for suf in _DERIVE_SUFFIXES:
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    snake = camel_to_snake(base)
    # Replace underscores with hyphens later in normalize; here keep snake
    out = snake.strip("_- .")
    if derived_lower:
        out = out.lower()
    return out


def derive_namespace_core(
        cls: Type,
        *,
        namespace_arg: Optional[str],
        namespace_attr: Optional[str],
) -> str:
    """
    Derive the `namespace` part (core logic; no Django).
    Precedence: decorator arg -> class attribute -> module root (left-most package segment) -> 'app'
    """
    if namespace_arg is not None and str(namespace_arg).strip():
        return str(namespace_arg).strip()

    if namespace_attr is not None and str(namespace_attr).strip():
        return str(namespace_attr).strip()

    module = getattr(cls, "__module__", "") or ""
    root = module.split(".", 1)[0] if module else "app"
    return root.strip()


def derive_kind(
        cls: Type, *,
        kind_arg: Optional[str],
        kind_attr: Optional[str],
        default: str = "default",
) -> str:
    """
    Derive the `kind` part.
    Precedence: decorator arg -> class attribute -> default ('default' by plan)
    """
    if kind_arg is not None and str(kind_arg).strip():
        return str(kind_arg).strip()

    if kind_attr is not None and str(kind_attr).strip():
        return str(kind_attr).strip()

    return default


def strip_name_tokens(name: str, tokens: Iterable[str]) -> str:
    """
    Remove tokens from the *name only*, case-insensitive, segment-aware.

    Segment-aware means we split on common separators (., _, -) and remove any segment
    that equals a token ignoring case. We then re-join with '-' (normalization will
    collapse duplicates and trim).
    """
    tokens = [t for t in (tokens or []) if t]
    if not tokens:
        return name

    # Build case-insensitive set for quick checks
    token_set = {t.lower() for t in tokens}

    parts = [p for p in _SEP_RE.split(name) if p]  # split to segments
    kept = [p for p in parts if p.lower() not in token_set]
    # Re-join with '-' to keep a consistent separator; normalize will finalize
    return "-".join(kept)


def normalize_name(name: str) -> str:
    """
    Normalize the name:
      - collapse runs of [._-] to single '-'
      - strip leading/trailing separators/spaces
      - prefer lowercase for derived names (explicit names may have been passed unchanged)
        (Callers control lower-casing when deriving; this function does not force lower)
    """
    # Collapse separators to hyphen
    s = _SEP_RE.sub("-", name)
    # Trim
    s = s.strip(" -._")
    # Collapse multiple hyphens
    s = re.sub(r"-{2,}", "-", s)
    return s


def validate_identity(namespace: str, kind: str, name: str) -> None:
    """
    Validate identity parts for basic structural safety.

    - Non-empty strings
    - Allowed characters: A–Z, a–z, 0–9, '.', '_', '-'
    - Reasonable length caps (128 each)

    Note: explicit names may include uppercase. This function does not force case;
    callers should normalize *before* validation when deriving names.
    """
    for label, value in (("namespace", namespace), ("kind", kind), ("name", name)):
        if not isinstance(value, str):
            raise IdentityError(f"{label} must be a string (got {type(value)!r})")
        v = value.strip()
        if not v:
            raise IdentityError(f"{label} cannot be empty")
        if len(v) > 128:
            raise IdentityError(f"{label} too long (>128)")
        if not _ALLOWED_RE.match(v):
            raise IdentityError(f"{label} contains illegal characters: {value!r}")


def derive_identity_core(
        cls: Type,
        *,
        namespace_arg: Optional[str] = None,
        kind_arg: Optional[str] = None,
        name_arg: Optional[str] = None,
        namespace_attr: Optional[str] = None,
        kind_attr: Optional[str] = None,
        name_attr: Optional[str] = None,
        name_tokens: Iterable[str] = (),
        lower_on_derived_name: bool = True,
) -> Identity:
    """
    Orchestrate core identity derivation (no Django).

    Steps:
      1) derive_name (explicit preserved, or derived+lower)
      2) derive_namespace (arg -> attr -> module root)
      3) derive_kind (arg -> attr -> 'default')
      4) strip tokens on name only (case-insensitive, segment-aware)
      5) normalize name (collapse separators)
      6) validate
      7) return Identity(namespace, kind, name)
    """
    name = derive_name(cls, name_arg=name_arg, name_attr=name_attr, derived_lower=lower_on_derived_name)
    # Only apply token stripping to names that were *not* explicitly provided
    # Heuristic: if name_arg or name_attr was provided, we already returned early in derive_name
    # so here we can always apply tokens (the caller can pass an empty token list to no-op).
    name = strip_name_tokens(name, name_tokens)
    name = normalize_name(name)

    namespace = derive_namespace_core(cls, namespace_arg=namespace_arg, namespace_attr=namespace_attr)
    kind = derive_kind(cls, kind_arg=kind_arg, kind_attr=kind_attr, default="default")

    validate_identity(namespace, kind, name)

    return Identity(namespace=namespace, kind=kind, name=name)
