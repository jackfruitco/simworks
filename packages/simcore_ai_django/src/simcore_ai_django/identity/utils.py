# simcore_ai_django/identity/utils.py
"""
Django-aware identity utilities for SimCore AI.

This module *extends* the core identity utilities with Django context:

- Derives `origin` from: explicit → class attr → Django app label → module_root → "default"
- Aggregates strip-token sets from:
    * Core DEFAULT_STRIP_TOKENS
    * "Django"
    * Global settings: settings.AI_IDENTITY_STRIP_TOKENS
    * App-specific: AppConfig.identity_strip_tokens (optional)
    * App label variants (case/slug)
    * Call-site provided tokens
- Normalizes all identity parts to snake_case
- Resolves collisions using Django's DEBUG setting

It also **re-exports** core helpers so projects can import them from the Django layer.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Callable, Optional, Tuple

from django.apps import AppConfig, apps
from django.conf import settings

from simcore_ai.identity.utils import (
    DEFAULT_STRIP_TOKENS,
    snake,
    strip_tokens,
    derive_name_from_class,
    module_root,
    derive_identity_for_class,
    resolve_collision,
    parse_dot_identity,
)

__all__ = [
    # Django-aware helpers
    "derive_django_identity_for_class",
    "get_app_label_for_class",
    "resolve_collision_django",
    # Re-exports from core for convenience
    "DEFAULT_STRIP_TOKENS",
    "snake",
    "strip_tokens",
    "derive_name_from_class",
    "module_root",
    "derive_identity_for_class",
    "resolve_collision",
    "parse_dot_identity",
]


@lru_cache(maxsize=128)
def _app_config_for_module(module: str) -> Optional[AppConfig]:
    """Return the Django AppConfig for a given module path, or None if not found."""
    for cfg in apps.app_configs.values():
        if module.startswith(cfg.name):
            return cfg
    return None


def get_app_label_for_class(cls: type) -> Optional[str]:
    """Return the Django app label for `cls`, if any."""
    module = getattr(cls, "__module__", None)
    if not module:
        return None
    cfg = _app_config_for_module(module)
    return getattr(cfg, "label", None) if cfg else None


def _app_label_token_variants(label: str) -> set[str]:
    """Build token variants from an app label (case variants and snake/slug forms)."""
    variants = {
        label,
        label.lower(),
        label.upper(),
        snake(label),
        label.replace("_", "-"),
        label.replace("-", "_"),
    }
    return {v for v in variants if v}


def _global_strip_tokens() -> set[str]:
    """Global extra tokens from settings.AI_IDENTITY_STRIP_TOKENS (optional)."""
    return set(getattr(settings, "AI_IDENTITY_STRIP_TOKENS", ()) or ())


def _app_strip_tokens(app_label: str) -> set[str]:
    """App-specific tokens from AppConfig.identity_strip_tokens (optional)."""
    cfg = apps.app_configs.get(app_label)
    return set(getattr(cfg, "identity_strip_tokens", ()) or ()) if cfg else set()


def derive_django_identity_for_class(
    cls: type,
    *,
    origin: Optional[str] = None,
    bucket: Optional[str] = None,
    name: Optional[str] = None,
    strip_tokens: Iterable[str] = (),
) -> Tuple[str, str, str]:
    """Derive `(origin, bucket, name)` for a class using Django context.

    Origin precedence:
      1) explicit `origin`
      2) class attribute `origin`
      3) Django app label
      4) module_root(cls)
      5) "default"

    Tokens used = DEFAULT_STRIP_TOKENS ∪ {"Django"} ∪ global settings ∪ app tokens ∪
    app-label variants ∪ provided `strip_tokens`. All outputs are snake-cased.
    """
    # Select origin with precedence
    if origin:
        use_origin = origin
    elif isinstance(getattr(cls, "origin", None), str) and getattr(cls, "origin"):
        use_origin = getattr(cls, "origin")
    else:
        app_label = get_app_label_for_class(cls)
        if app_label:
            use_origin = app_label
        else:
            use_origin = module_root(cls) or "default"

    # Build token set
    app_label = get_app_label_for_class(cls)
    tokens = set(DEFAULT_STRIP_TOKENS)
    tokens.add("Django")
    tokens.update(_global_strip_tokens())
    if app_label:
        tokens.update(_app_strip_tokens(app_label))
        tokens.update(_app_label_token_variants(app_label))
    if strip_tokens:
        tokens.update(strip_tokens)

    # Delegate to core derivation with computed origin and unioned tokens
    o, b, n = derive_identity_for_class(
        cls,
        origin=use_origin,
        bucket=bucket,
        name=name,
        strip_tokens=tokens,
    )
    # Defensive normalization
    return snake(o), snake(b), snake(n)


def resolve_collision_django(
    kind: str,
    ident: Tuple[str, str, str],
    *,
    exists: Callable[[Tuple[str, str, str]], bool],
) -> Tuple[str, str, str]:
    """Resolve identity collisions using Django's DEBUG setting for policy.

    In DEBUG → raise; in non-DEBUG → warn + append '-2', '-3', … to the name.
    """
    return resolve_collision(kind, ident, debug=getattr(settings, "DEBUG", False), exists=exists)