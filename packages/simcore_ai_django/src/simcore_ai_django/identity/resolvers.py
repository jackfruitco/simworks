# simcore_ai_django/identity/resolvers.py
"""Django-aware identity resolver for SimCore AI decorators.

This module provides a pluggable identity resolver used by Django-side
decorators (prompt sections, services, codecs). It derives a canonical
(origin, bucket, name) tuple with awareness of Django apps and project
settings and supports standardized token stripping.

Key behaviors:
- Uses the leaf concrete class/function to derive `name` (mixin-safe).
- Standardized suffix stripping across domains, with Django-specific tokens.
- Collects extra strip tokens from:
  * AppConfig.AI_IDENTITY_STRIP_TOKENS (if defined)
  * settings.SIMCORE_AI_IDENTITY_STRIP_TOKENS (if defined)
- Bucket defaults to "default" when not specified by overrides or derivation.

This module must not import any registry code to avoid circular imports.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from django.apps import apps
from django.conf import settings

from simcore_ai_django.identity import derive_django_identity_for_class

__all__ = ["django_identity_resolver"]

# Core-standard suffix/tokens to strip (agreed project-wide)
_CORE_STRIP: tuple[str, ...] = (
    "Prompt",
    "Section",
    "Service",
    "Codec",
    "Generate",
    "Response",
    "Mixin",
)
# Django adds this token; app/settings may add more.
_DJANGO_EXTRA: tuple[str, ...] = ("Django",)


def _iter_app_and_project_tokens(obj: object) -> Iterable[str]:
    """Yield extra identity strip tokens from the app and project settings.

    Looks for:
      - AppConfig.AI_IDENTITY_STRIP_TOKENS (list/tuple[str]) for the app
        containing the object's module (if any)
      - settings.SIMCORE_AI_IDENTITY_STRIP_TOKENS (list/tuple[str])
    """
    # App-level tokens
    mod = getattr(obj, "__module__", "") or ""
    app_cfg = apps.get_containing_app_config(mod)
    if app_cfg is not None:
        tokens = getattr(app_cfg, "AI_IDENTITY_STRIP_TOKENS", None)
        if isinstance(tokens, (list, tuple)):
            for t in tokens:
                if isinstance(t, str) and t:
                    yield t

    # Project-level tokens
    proj_tokens = getattr(settings, "SIMCORE_AI_IDENTITY_STRIP_TOKENS", None)
    if isinstance(proj_tokens, (list, tuple)):
        for t in proj_tokens:
            if isinstance(t, str) and t:
                yield t


def _collect_tokens(obj: object) -> Tuple[str, ...]:
    """Collect the full set of strip tokens for this object.

    Returns a tuple combining core-standard tokens, Django token, and any
    app/settings-provided tokens.
    """
    dynamic = tuple(_iter_app_and_project_tokens(obj))
    return tuple(*_CORE_STRIP, *_DJANGO_EXTRA, *dynamic)


def django_identity_resolver(
        obj: object,
        *,
        origin: Optional[str],
        bucket: Optional[str],
        name: Optional[str],
) -> tuple[str, str, str]:
    """Resolve (origin, bucket, name) using Django-aware rules.

    - Delegates to `derive_django_identity_for_class`, passing through any
      explicit overrides and the collected strip tokens.
    - Works with both classes and generated service classes; if a function is
      passed, its generated service class should be used by the caller (the
      factory in core handles this).
    - Ensures bucket defaults to "default" if empty after derivation.
    """
    tokens = _collect_tokens(obj)

    # We call the Django-aware derive function on the object (class). The core
    # service factory ensures that for functions we pass the generated class.
    org, buck, nm = derive_django_identity_for_class(
        obj, origin=origin, bucket=bucket, name=name, strip_tokens=tokens
    )

    if not buck:
        buck = "default"

    return org, buck, nm
