# packages/simcore_ai_django/src/simcore_ai_django/settings.py


"""
Package-level configuration helpers & defaults for `simcore_ai_django`.

This is **not** your project's Django `settings.py`. It provides internal
accessors with sane defaults that can be overridden by the Django project's
`django.conf.settings`.

Keys used across the Django layer:
- SIMCORE_COLLISIONS_STRICT: bool
    Controls registry behavior on identity collisions. Defaults to True.
- SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL: Iterable[str]
    Case-insensitive tokens stripped from the *name* portion of identities,
    in addition to per-app tokens. Defaults to empty tuple ().

Notes:
- We do not import or modify the project's settings structure; we only read
  values when asked, falling back to internal defaults.
- Keep this small and dependency-free so it can be imported anywhere.
"""

from typing import Any, Tuple

try:  # Django may not be fully configured in certain tooling contexts
    from django.conf import settings as dj_settings
except Exception:  # pragma: no cover - defensive import guard
    dj_settings = None  # type: ignore[assignment]

# ----------------------------
# Internal defaults
# ----------------------------
DEFAULTS = {
    # Single strictness knob for identity collisions across all registries
    "SIMCORE_COLLISIONS_STRICT": True,

    # Global tokens applied to the *name* part only (case-insensitive)
    # Per-app tokens should come from AppConfig.IDENTITY_STRIP_TOKENS
    "SIMCORE_IDENTITY_STRIP_TOKENS": tuple(),  # type: Tuple[str, ...]
}


# ----------------------------
# Accessors
# ----------------------------

def get_setting(key: str, default: Any | None = None) -> Any:
    """Return a setting from the Django project or fallback to defaults.

    The lookup order is: project settings -> provided default -> internal DEFAULTS.
    """
    if dj_settings is not None and hasattr(dj_settings, key):
        return getattr(dj_settings, key)
    if default is not None:
        return default
    return DEFAULTS.get(key)


def get_bool(key: str, default: bool | None = None) -> bool:
    """Coerce a setting to boolean with a sensible fallback."""
    val = get_setting(key, default if default is not None else DEFAULTS.get(key, False))
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def get_tokens_global() -> Tuple[str, ...]:
    """Return global identity strip tokens as a tuple of strings (CI semantics elsewhere)."""
    val: Any = get_setting("SIMCORE_IDENTITY_STRIP_TOKENS", DEFAULTS["SIMCORE_IDENTITY_STRIP_TOKENS"])
    # Normalize into a tuple[str, ...]
    if val is None:
        return tuple()
    if isinstance(val, (list, tuple, set)):
        return tuple(str(x) for x in val if isinstance(x, str))
    # Single string: allow comma-separated or space-separated for convenience
    if isinstance(val, str):
        raw = [p.strip() for p in val.replace(",", " ").split() if p.strip()]
        return tuple(raw)
    # Unknown type: fallback safely
    return tuple()


# Convenience aliases used throughout the package
STRICT_COLLISIONS: bool = get_bool("SIMCORE_COLLISIONS_STRICT", DEFAULTS["SIMCORE_COLLISIONS_STRICT"])
GLOBAL_NAME_TOKENS: Tuple[str, ...] = get_tokens_global()

__all__ = [
    "get_setting",
    "get_bool",
    "get_tokens_global",
    "STRICT_COLLISIONS",
    "GLOBAL_NAME_TOKENS",
]
