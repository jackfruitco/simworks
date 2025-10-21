# simcore_ai_django/decorators/mixins.py
"""Django-aware identity & token mixins for class-based registration decorators.

This module provides two focused mixins:

- `DjangoStripTokensMixin`
    Extends the base decorator's token collection by merging additional sources:
      * Core defaults from `BaseRegistrationDecorator.strip_tokens()`
      * Core env: `SIMCORE_AI_IDENTITY_STRIP_TOKENS`
      * Django package defaults (this module)
      * Django env: `SIMCORE_AI_DJANGO_IDENTITY_STRIP_TOKENS`
      * Django settings: `settings.SIMCORE_AI_IDENTITY_STRIP_TOKENS`
      * AppConfig contributions gathered at startup (optional, best-effort)
        via `simcore_ai_django.identity.get_app_identity_strip_tokens()` or
        a module-global `APP_IDENTITY_STRIP_TOKENS` set.

- `DjangoIdentityResolverMixin`
    Produces **Django-aware** module defaults for `(origin, bucket)` using
    `django.apps.apps.get_containing_app_config` when available, while keeping
    the same semantics as the core resolver:
      * Precedence: kwargs > class attrs > Django/module-derived defaults
      * Strip tokens from **name only** (both ends, case-insensitive, iterative)
      * Snake-case all three parts using the shared `snake` helper

Use `DjangoSimcoreIdentityMixin` to combine both concerns in a single base for
domain decorators (e.g., services, codecs, prompt sections, schemas).

These mixins are intentionally safe at import time: they degrade gracefully
when Django settings are not configured or apps are not ready.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any, Optional, Tuple

log = logging.getLogger(__name__)

from simcore_ai.decorators.registration import BaseRegistrationDecorator
from simcore_ai.identity.utils import snake

# --- Django-light imports (guarded) ---
try:  # pragma: no cover
    from django.conf import settings  # type: ignore
except Exception:  # pragma: no cover
    class _SettingsShim:
        def __getattr__(self, _name: str) -> Any:
            raise AttributeError(_name)


    settings = _SettingsShim()  # type: ignore

try:  # pragma: no cover
    from django.apps import apps  # type: ignore
except Exception:  # pragma: no cover
    class _AppsShim:
        def get_containing_app_config(self, _mod: str):
            return None


    apps = _AppsShim()  # type: ignore

# --- Defaults specific to Django layer (kept minimal) ---
DJANGO_DEFAULT_STRIP_TOKENS: Tuple[str, ...] = (
    # domain-ish suffixes or prefixes we commonly see around Django apps
    "Django",
    "Model",
    "View",
    "Form",
    "Serializer",
    # project-specific common token
    "Patient",
)


def _iter_setting_tokens() -> Iterable[str]:
    """Yield tokens from Django settings if available."""
    try:
        tokens = getattr(settings, "SIMCORE_AI_IDENTITY_STRIP_TOKENS", None)
        if tokens:
            for t in tokens:
                if isinstance(t, str):
                    yield t
    except Exception:
        return


def _iter_env_tokens() -> Iterable[str]:
    """Yield tokens from Django-specific env var."""
    raw = os.environ.get("SIMCORE_AI_DJANGO_IDENTITY_STRIP_TOKENS", "")
    for t in (x.strip() for x in raw.split(",") if x.strip()):
        yield t


def _iter_app_tokens() -> Iterable[str]:
    """Yield tokens contributed by Django AppConfigs via a central store (best-effort)."""
    try:
        # Preferred: a callable that returns an iterable
        from simcore_ai_django.identity import get_app_identity_strip_tokens  # type: ignore
        try:
            contrib = get_app_identity_strip_tokens()
            for t in contrib or ():
                if isinstance(t, str):
                    yield t
            return
        except Exception:
            pass
    except Exception:
        pass

    # Fallback: a module-level set/tuple
    try:
        from simcore_ai_django import identity  # type: ignore
        contrib2 = getattr(identity, "APP_IDENTITY_STRIP_TOKENS", None)
        if contrib2:
            for t in contrib2:
                if isinstance(t, str):
                    yield t
    except Exception:
        return


class DjangoStripTokensMixin(BaseRegistrationDecorator):
    """Mixin that augments `collect_strip_tokens` with Django-aware sources."""

    def collect_strip_tokens(self, extra_tokens: Optional[Iterable[str]] = None) -> set[str]:  # type: ignore[override]
        # Start with core tokens + any explicit extras (from decorator kwargs call site)
        tokens = set(super().collect_strip_tokens(extra_tokens))
        # Merge Django package defaults
        tokens.update(DJANGO_DEFAULT_STRIP_TOKENS)
        # Merge env (Django-specific)
        tokens.update(_iter_env_tokens())
        # Merge settings-driven tokens
        tokens.update(_iter_setting_tokens())
        # Merge AppConfig contributions
        tokens.update(_iter_app_tokens())
        return tokens


class DjangoIdentityResolverMixin(BaseRegistrationDecorator):
    """Mixin that makes identity resolution Django-app aware.

    Derives better module defaults for `(origin, bucket)` by inspecting
    the owning Django AppConfig (when available). Name stripping and
    snake-casing rules mirror the core behavior.
    """

    def _django_module_defaults(self, obj: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Best-effort `(origin, bucket, name)` defaults from Django app metadata."""
        try:
            mod = getattr(obj, "__module__", "") or ""
            appcfg = apps.get_containing_app_config(mod)
            if not appcfg:
                return None, None, None

            # origin: prefer `label`, else root of dotted app name
            origin_raw = getattr(appcfg, "label", None) or getattr(appcfg, "name", "").split(".")[0] or None

            # bucket: if module is under the app package, use first segment after the app package
            bucket_raw: Optional[str] = None
            app_pkg = getattr(appcfg, "name", "") or ""
            if app_pkg and mod.startswith(app_pkg + "."):
                parts = mod.split(".")
                app_parts = app_pkg.split(".")
                if len(parts) > len(app_parts):
                    bucket_raw = parts[len(app_parts)]
            # common fallback if present in module path
            if not bucket_raw and "ai" in (mod.split(".") if mod else ()):
                bucket_raw = "ai"

            # name: use the object __name__ (strip handled upstream)
            name_raw = getattr(obj, "__name__", None) or None
            return origin_raw, bucket_raw, name_raw
        except Exception:
            return None, None, None

    def resolve_identity(
            self,
            obj: Any,
            *,
            origin: Optional[str] = None,
            bucket: Optional[str] = None,
            name: Optional[str] = None,
    ) -> tuple[str, str, str]:  # type: ignore[override]
        """Resolve identity with Django-aware defaults; strip tokens on **name** only."""
        # 1) Try kwargs first
        o_raw = origin
        b_raw = bucket
        n_raw = name

        # 2) Then class attributes
        if o_raw is None:
            o_raw = getattr(obj, "origin", None)
        if b_raw is None:
            b_raw = getattr(obj, "bucket", None)
        if n_raw is None:
            n_raw = getattr(obj, "name", None)

        # 3) Then Django-aware module defaults
        if o_raw is None or b_raw is None or n_raw is None:
            do, db, dn = self._django_module_defaults(obj)
            o_raw = o_raw if o_raw is not None else do
            b_raw = b_raw if b_raw is not None else db
            n_raw = n_raw if n_raw is not None else dn

        # 4) Finally, fall back to base module-derived defaults if still missing
        if o_raw is None or b_raw is None or n_raw is None:
            # Use base resolver to fill in any gaps
            o2, b2, n2 = super().resolve_identity(obj, origin=None, bucket=None, name=None)
            o_raw = o_raw if o_raw is not None else o2
            b_raw = b_raw if b_raw is not None else b2
            n_raw = n_raw if n_raw is not None else n2

        # Normalize and strip **name** only using the complete token set
        tokens = self.collect_strip_tokens()
        name_stripped = self._strip_affixes_casefold(str(n_raw), tokens)
        return snake(str(o_raw)), snake(str(b_raw)), snake(str(name_stripped))


class DjangoSimcoreIdentityMixin(DjangoStripTokensMixin, DjangoIdentityResolverMixin):
    """Convenience combiner: Django token sources + Django-aware identity resolution."""
    pass


__all__ = [
    "DjangoStripTokensMixin",
    "DjangoIdentityResolverMixin",
    "DjangoSimcoreIdentityMixin",
]
