# orchestrai/identity/utils.py
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
- *Derivation* of identities is handled by `orchestrai.identity.resolution.IdentityResolver`.
  This module intentionally no longer exposes `derive_identity_for_class`.
"""



import logging
import os
import re
from collections.abc import Iterable, Callable
from typing import Optional, Union, TYPE_CHECKING, Any

from .exceptions import IdentityError

if TYPE_CHECKING:
    from . import IdentityLike, Identity

__all__ = [
    "DEFAULT_IDENTITY_STRIP_TOKENS",
    "strip_tokens",
    "snake",
    "module_root",
    "resolve_collision",
    "parse_dot_identity",
    "get_effective_strip_tokens",
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
_DEBUG_FALLBACK = _env_truthy(os.getenv("orchestrai_DEBUG"))


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


def _as_list_from_maybe_csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [t for t in re.split(r"[\s,]+", value.strip()) if t]
    if isinstance(value, (list, tuple)):
        return [str(t) for t in value if isinstance(t, str) and t]
    return []


def _tokens_from_settings() -> list[str]:
    try:
        from orchestrai._state import get_current_app

        app = get_current_app()
        conf = getattr(app, "conf", None)
    except Exception:
        return []

    if conf is None:
        return []

    try:
        value = conf.get("IDENTITY_STRIP_TOKENS")
    except Exception:
        value = getattr(conf, "IDENTITY_STRIP_TOKENS", None)

    return _as_list_from_maybe_csv(value)


def _tokens_from_env() -> list[str]:
    env_value = os.getenv("IDENTITY_STRIP_TOKENS") or os.getenv("SIMCORE_IDENTITY_STRIP_TOKENS")
    return _as_list_from_maybe_csv(env_value)


def _persist_tokens_on_app(tokens: tuple[str, ...]) -> None:
    try:
        from orchestrai._state import get_current_app

        app = get_current_app()
        conf = getattr(app, "conf", None)
        if conf is not None:
            conf["IDENTITY_STRIP_TOKENS"] = tokens
    except Exception:
        logger.debug("Failed to persist IDENTITY_STRIP_TOKENS on current app", exc_info=True)


def get_effective_strip_tokens(extra_tokens: Iterable[str] = ()) -> tuple[str, ...]:
    """Return the effective strip tokens merged from defaults, settings, env, extras."""

    base_tokens = list(DEFAULT_IDENTITY_STRIP_TOKENS)
    settings_tokens = _tokens_from_settings()
    env_tokens = _tokens_from_env()
    extra_list = list(extra_tokens or [])

    merged: list[str] = []
    seen: set[str] = set()

    for source in (base_tokens, settings_tokens, env_tokens, extra_list):
        for t in source:
            if not isinstance(t, str) or not t:
                continue
            key = t.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(t)

    merged_tuple = tuple(merged)
    _persist_tokens_on_app(merged_tuple)
    return merged_tuple


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

    # Build the case-insensitive token set from effective tokens
    effective_tokens = get_effective_strip_tokens(extra_tokens)
    token_set = {t.casefold() for t in effective_tokens}

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
        debug: If None, falls back to orchestrai_DEBUG env var.
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


def coerce_identity_key(value: "IdentityLike" | None) -> tuple[str, str, str] | None:
    """Best-effort conversion of Identity-like inputs to an (namespace, kind, name) tuple."""

    if value is None:
        return None

    try:
        from .identity import Identity

        ident = Identity.get(value)
    except IdentityError:
        logger.debug("Failed to coerce identity value: %r", value)
        return None

    return ident.as_tuple3

