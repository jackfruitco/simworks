# packages/simcore_ai_django/src/simcore_ai_django/decorators/helpers.py
from __future__ import annotations

"""
Django-aware helpers for identity derivation and name token stripping.

These helpers extend the core (provider-agnostic) helpers with Django context:
- deriving the `namespace` prefers Django app label, then app name, then module root
- collecting per-app and optional global tokens for *name-only* stripping
- case-insensitive, segment-aware stripping (delegates to core implementation)

Note: Do not import these from the core package. They are used only by
`simcore_ai_django.decorators.base.DjangoBaseDecorator`.
"""

from typing import Iterable, Optional, Tuple, Type, List

from django.apps import apps, AppConfig
from django.conf import settings

from simcore_ai.tracing import service_span_sync

from simcore_ai.decorators.helpers import (
    strip_name_tokens as core_strip_name_tokens,
)


# -----------------------------
# App resolution helpers
# -----------------------------

def _get_app_config_for_class(cls: Type) -> Optional[AppConfig]:
    """
    Attempt to resolve the Django AppConfig that owns the given class by
    inspecting its module path and matching on `app_config.name` prefix.
    """
    module = getattr(cls, "__module__", "") or ""
    for cfg in apps.get_app_configs():
        if module.startswith(cfg.name):
            return cfg
    return None


def derive_namespace_django(
        cls: Type,
        *,
        namespace_arg: Optional[str],
        namespace_attr: Optional[str],
) -> str:
    """
    Derive the `namespace` with Django precedence:
      1) explicit decorator argument
      2) explicit class attribute
      3) Django app label
      4) Django app name
      5) module root (left-most package segment) or 'app'
    """
    # 1) explicit arg
    if namespace_arg is not None and str(namespace_arg).strip():
        return str(namespace_arg).strip()

    # 2) class attribute
    if namespace_attr is not None and str(namespace_attr).strip():
        return str(namespace_attr).strip()

    # 3/4) Django app label/name
    cfg = _get_app_config_for_class(cls)
    if cfg is not None:
        label = getattr(cfg, "label", None)
        if label:
            return str(label).strip()
        name = getattr(cfg, "name", None)
        if name:
            return str(name).strip()

    # 5) module root fallback (provider-agnostic behavior)
    module = getattr(cls, "__module__", "") or ""
    root = module.split(".", 1)[0] if module else "app"
    return root.strip()


# -----------------------------
# Name token collection & stripping
# -----------------------------

def _dedupe_ci(tokens: Iterable[str]) -> Tuple[str, ...]:
    seen = set()
    out: List[str] = []
    for t in tokens or ():
        if not isinstance(t, str):
            continue
        k = t.casefold()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return tuple(out)


def get_app_tokens_for_name(cls: Type) -> Tuple[str, ...]:
    """
    Collect case-insensitive, de-duplicated tokens used to strip *from the name only*.

    Sources (in order):
      - AppConfig.IDENTITY_STRIP_TOKENS (if present)
      - settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL (optional, iterable)

    Tokens are de-duplicated case-insensitively while preserving first occurrence order.
    """
    with service_span_sync(
        "ai.django.collect_tokens",
        attributes={
            "ai.class": f"{cls.__module__}.{cls.__name__}",
        },
    ) as span:
        tokens: List[str] = []

        cfg = _get_app_config_for_class(cls)
        if cfg is not None:
            app_tokens = getattr(cfg, "IDENTITY_STRIP_TOKENS", None)
            if app_tokens:
                try:
                    for t in app_tokens:
                        if isinstance(t, str):
                            tokens.append(t)
                except Exception:
                    # Be defensive about arbitrary iterables
                    pass

        global_tokens = getattr(settings, "SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL", None)
        if global_tokens:
            try:
                for t in global_tokens:
                    if isinstance(t, str):
                        tokens.append(t)
            except Exception:
                pass

        attrs = {
            "ai.tokens.app_count": len(tokens),
            "ai.tokens.global_count": len(global_tokens or []),
        }
        for k, v in attrs.items():
            try:
                span.set_attribute(k, v)
            except Exception:
                # never break token collection due to tracing issues
                pass

        return _dedupe_ci(tokens)


def strip_name_tokens_django(name: str, tokens: Iterable[str]) -> str:
    """
    Delegate to the core, case-insensitive, segment-aware name-only stripping.
    Provided here for symmetry and potential future Django-specific behavior.
    """
    return core_strip_name_tokens(name, tokens)
