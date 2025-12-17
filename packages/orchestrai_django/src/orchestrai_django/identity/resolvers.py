"""
Django-aware identity resolver.

Subclass of the core IdentityResolver that:
- infers `namespace` from (arg → class attr → Django app label → module root → "default"),
- collects strip tokens from core defaults + Django sources:
  * DJANGO_BASE_STRIP_TOKENS = ("Django", "Mixin")
  * settings.ORCA_IDENTITY_STRIP_TOKENS (list/tuple/CSV) (SIMCORE_* accepted for back-compat)
  * AppConfig.IDENTITY_STRIP_TOKENS (list/tuple)
  * App label variants (label, snake(label), hyphen/underscore forms)

No decorator/registry imports here to avoid cycles.
"""

import os
import re
import logging
from typing import Any, Optional, TYPE_CHECKING

from django.apps import apps
from django.conf import settings

from orchestrai.identity.resolvers import IdentityResolver
from orchestrai.identity.utils import get_effective_strip_tokens, snake, module_root

if TYPE_CHECKING:  # type-only import to avoid runtime cycles
    from orchestrai.identity import Identity

__all__ = [
    "DjangoIdentityResolver",
    "resolve_identity_django",
        "q  a",
]


logger = logging.getLogger(__name__)

# Default tokens to strip from class names in Django deployments.
# These are added on top of core defaults via `get_effective_strip_tokens(...)`.
DJANGO_BASE_STRIP_TOKENS: tuple[str, ...] = (
    "Django",
    "Mixin",
)


def _default_orca_app_from_django_settings():
    """Best-effort access to the default OrchestrAI app stored by orchestrai_django.apps."""
    # orchestrai_django.apps should set one of these during AppConfig.ready()
    return (
        getattr(settings, "_ORCA_APP", None)
        or getattr(settings, "ORCA_APP", None)
        or getattr(settings, "_ORCHESTRAI_APP", None)
        or getattr(settings, "ORCHESTRAI_APP", None)
    )


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


def _project_strip_tokens_from_settings() -> list[str]:
    """Project-level strip tokens.

    Preferred source:
      - the merged OrchestrAI app settings (app.ensure_settings().IDENTITY_STRIP_TOKENS)

    Fallbacks (for early import / misconfiguration cases):
      - Django settings: ORCA_IDENTITY_STRIP_TOKENS, ORCA dict, SIMCORE_* (back-compat)
    """
    # Preferred: merged settings on the default OrchestrAI app
    app = _default_orca_app_from_django_settings()
    if app is not None and hasattr(app, "ensure_settings") and callable(getattr(app, "ensure_settings")):
        try:
            merged = app.ensure_settings()
            val = getattr(merged, "IDENTITY_STRIP_TOKENS", None)
            if val is None and isinstance(merged, dict):
                val = merged.get("IDENTITY_STRIP_TOKENS") or merged.get("identity_strip_tokens")
            if val is not None:
                return _as_list_from_maybe_csv(val)
        except Exception:
            # Don't crash identity import if the app isn't ready yet.
            logger.debug("Failed to read IDENTITY_STRIP_TOKENS from default OrchestrAI app", exc_info=True)

    # Fallback: explicit ORCA_* setting
    if hasattr(settings, "ORCA_IDENTITY_STRIP_TOKENS"):
        return _as_list_from_maybe_csv(getattr(settings, "ORCA_IDENTITY_STRIP_TOKENS"))

    # Fallback: ORCA dict setting
    orca_cfg = getattr(settings, "ORCA", None)
    if isinstance(orca_cfg, dict):
        val = orca_cfg.get("IDENTITY_STRIP_TOKENS") or orca_cfg.get("identity_strip_tokens")
        if val is not None:
            return _as_list_from_maybe_csv(val)

    # Back-compat: SIMCORE_* setting
    if hasattr(settings, "SIMCORE_IDENTITY_STRIP_TOKENS"):
        return _as_list_from_maybe_csv(getattr(settings, "SIMCORE_IDENTITY_STRIP_TOKENS"))

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
        extra: list[str] = []

        # Add Django base tokens
        extra.extend(DJANGO_BASE_STRIP_TOKENS)

        # Project-level settings (any of CSV/list/tuple)
        extra.extend(_project_strip_tokens_from_settings())

        # App-level tokens (list/tuple) and label variants
        cfg = _app_config_for_class(cls)
        if cfg is not None:
            app_tokens = getattr(cfg, "IDENTITY_STRIP_TOKENS", None)
            extra.extend(_as_list_from_maybe_csv(app_tokens))
            # Include app label variants so class names like `ChatlabPatient...` strip cleanly
            label = getattr(cfg, "label", "")
            extra.extend(_app_label_variants(label))

        # Env override (ORCA preferred; SIMCORE accepted for back-compat)
        env_val = os.getenv("ORCA_IDENTITY_STRIP_TOKENS") or os.getenv("SIMCORE_IDENTITY_STRIP_TOKENS", "")
        extra.extend(_as_list_from_maybe_csv(env_val))

        # Merge with core defaults + case-insensitive de-dupe
        return get_effective_strip_tokens(extra)


# Convenience helper mirroring the core one
def resolve_identity_django(
        cls: type,
        *,
        domain: Optional[str] = None,
        namespace: Optional[str] = None,
        group: Optional[str] = None,
        name: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
) -> tuple["Identity", dict[str, Any]]:
    r = DjangoIdentityResolver()
    ident, meta = r.resolve(
        cls,
        domain=domain,
        namespace=namespace,
        group=group,
        name=name,
        context=context,
    )
    return ident, meta
