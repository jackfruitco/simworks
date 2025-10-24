from __future__ import annotations

"""
Django-aware identity resolver.

Subclass of the core IdentityResolver that:
- infers `namespace` from (arg → class attr → Django app label → module root → "default"),
- collects strip tokens from core defaults + Django sources:
  * DJANGO_BASE_STRIP_TOKENS = ("Django", "Mixin")
  * settings.SIMCORE_IDENTITY_STRIP_TOKENS (list/tuple/CSV)
  * AppConfig.IDENTITY_STRIP_TOKENS (list/tuple)
  * App label variants (label, snake(label), hyphen/underscore forms)

No decorator/registry imports here to avoid cycles.
"""

import os
import re
from typing import Any, Optional

from django.apps import apps
from django.conf import settings

from simcore_ai.identity.resolution import IdentityResolver
from simcore_ai.identity.utils import DEFAULT_IDENTITY_STRIP_TOKENS, snake, module_root

__all__ = [
    "DjangoIdentityResolver",
    "resolve_identity_django",
]

# Base Django tokens to always strip for *derived* names
DJANGO_BASE_STRIP_TOKENS: tuple[str, ...] = ("Django", "Mixin")


def _as_list_from_maybe_csv(value: Any) -> list[str]:
    """Accept CSV string, list, or tuple; return list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        # split by comma/whitespace
        parts = re.split(r"[\s,]+", value.strip())
        return [p for p in parts if p]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, str) and v]
    return []


def _app_config_for_class(cls: type):
    module = getattr(cls, "__module__", "")
    try:
        return apps.get_containing_app_config(module)
    except Exception:
        return None


def _app_label_variants(label: str) -> list[str]:
    """Case and separator variants of an app label for token stripping."""
    if not label:
        return []
    sn = snake(label)
    return list({
        label,
        label.lower(),
        label.upper(),
        sn,
        sn.replace("_", "-"),
        label.replace("-", "_"),
    })


class DjangoIdentityResolver(IdentityResolver):
    """Django-aware resolver overriding namespace inference and token collection."""

    # ---- hook overrides ----
    def _resolve_namespace(
            self,
            cls: type,
            namespace_arg: Optional[str],
            namespace_attr: Optional[str],
    ) -> tuple[str, str]:
        # arg wins
        if isinstance(namespace_arg, str) and namespace_arg.strip():
            return namespace_arg.strip(), "arg"
        # class attr next
        if isinstance(namespace_attr, str) and namespace_attr.strip():
            return namespace_attr.strip(), "attr"
        # Django app label
        cfg = _app_config_for_class(cls)
        if cfg is not None and getattr(cfg, "label", None):
            return str(cfg.label), "derived"
        # fallback to module root, then default (the base will snake-case)
        root = module_root(cls) or "default"
        return root, "derived"

    def _collect_strip_tokens(self, cls: type) -> tuple[str, ...]:
        # Start with core defaults
        tokens: list[str] = list(DEFAULT_IDENTITY_STRIP_TOKENS)
        # Add Django base tokens
        tokens.extend(DJANGO_BASE_STRIP_TOKENS)

        # Project-level settings (any of CSV/list/tuple)
        project_tokens = []
        if hasattr(settings, "SIMCORE_IDENTITY_STRIP_TOKENS"):
            project_tokens = _as_list_from_maybe_csv(getattr(settings, "SIMCORE_IDENTITY_STRIP_TOKENS"))
        tokens.extend(project_tokens)

        # App-level tokens (list/tuple) and label variants
        cfg = _app_config_for_class(cls)
        if cfg is not None:
            app_tokens = getattr(cfg, "IDENTITY_STRIP_TOKENS", None)
            tokens.extend(_as_list_from_maybe_csv(app_tokens))
            # Include app label variants so class names like `ChatlabPatient...` strip cleanly
            label = getattr(cfg, "label", "")
            tokens.extend(_app_label_variants(label))

        # Env override (mirrors core env name for consistency)
        env_val = os.getenv("SIMCORE_IDENTITY_STRIP_TOKENS", "")
        tokens.extend(_as_list_from_maybe_csv(env_val))

        # De-duplicate case-insensitively preserving first-seen order
        seen: set[str] = set()
        dedup: list[str] = []
        for t in tokens:
            if not isinstance(t, str) or not t:
                continue
            key = t.casefold()
            if key not in seen:
                seen.add(key)
                dedup.append(t)
        return tuple(dedup)


# Convenience helper mirroring the core one

def resolve_identity_django(
        cls: type,
        *,
        namespace: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
) -> tuple["Identity", dict[str, Any]]:
    r = DjangoIdentityResolver()
    ident, meta = r.resolve(cls, namespace=namespace, kind=kind, name=name, context=context)
    return ident, meta
