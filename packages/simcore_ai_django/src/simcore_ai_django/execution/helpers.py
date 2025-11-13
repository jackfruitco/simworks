# simcore_ai_django/execution/helpers.py
from __future__ import annotations

"""
Helpers for execution entrypoint:
  - settings accessors
  - tracing attribute extraction (identity-aware)
  - backend lookup (re-export from registry)
"""

from collections.abc import Mapping
from typing import Any, Dict, Optional

from django.conf import settings

from simcore_ai.identity.utils import coerce_identity_key
from simcore_ai.tracing.helpers import flatten_context as flatten_context_attrs

from .registry import register_backend

__all__ = [
    "get_settings_dict",
    "settings_default_backend",
    "settings_default_mode",
    "settings_default_queue_name",
    "span_attrs_from_ctx",
]


# -------------------- Settings helpers --------------------
def get_settings_dict() -> Dict[str, Any]:
    """Return SIMCORE_AI_EXECUTION settings or an empty dict."""
    return getattr(settings, "SIMCORE_AI_EXECUTION", {}) or {}


def settings_default_backend() -> str:
    """Return normalized default execution backend ('immediate' fallback)."""
    return str(get_settings_dict().get("DEFAULT_BACKEND", "immediate")).strip().lower()


def settings_default_mode() -> str:
    """Return normalized default execution mode ('sync' fallback)."""
    return str(get_settings_dict().get("DEFAULT_MODE", "sync")).strip().lower()


def settings_default_queue_name() -> Optional[str]:
    """Return the default Celery queue name if configured, else None."""
    backends = get_settings_dict().get("BACKENDS", {}) or {}
    celery_cfg = backends.get("celery", {}) or {}
    q = celery_cfg.get("queue_default")
    return str(q).strip() if q else None


# -------------------- Tracing attribute helper --------------------

def _coerce_service_identity_from_ctx(ctx: Mapping[str, Any]) -> Optional[str]:
    """
    Best-effort extraction of a canonical 'namespace.kind.name' from ctx.
    Accepts:
      - ctx["identity"] (Identity | tuple3 | 'ns.kind.name')
      - ctx["service_identity"] / ctx["service_identity_str"]
      - fallback to discrete keys: namespace/kind/name (or service_bucket/service_name)
    """
    # 1) Direct identity object/tuple/string
    for key in ("identity", "service_identity"):
        val = ctx.get(key)
        if val is not None:
            key3 = coerce_identity_key(val)
            if key3:
                ns, kd, nm = key3
                return f"{ns}.{kd}.{nm}"

    # 2) Precomputed string
    for key in ("identity_str", "service_identity_str"):
        sval = ctx.get(key)
        if isinstance(sval, str) and sval.strip():
            # Validate/normalize if possible
            key3 = coerce_identity_key(sval)
            if key3:
                ns, kd, nm = key3
                return f"{ns}.{kd}.{nm}"
            return sval.strip()

    # 3) Assemble from discrete parts
    ns = ctx.get("namespace")
    kind = ctx.get("kind") or ctx.get("service_bucket")
    name = ctx.get("name") or ctx.get("service_name")
    if ns or kind or name:
        # If we can coerce, prefer canonical normalization
        key3 = coerce_identity_key((ns or "default", kind or "default", name or "default"))
        if key3:
            ns, kd, nm = key3
            return f"{ns}.{kd}.{nm}"
        return ".".join(x for x in (ns, kind, name) if x) or None

    return None


def span_attrs_from_ctx(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Build standard span attributes from an execution context mapping.

    - ai.identity.service: canonical 'namespace.kind.name' if resolvable
    - ai.identity.codec:   codec identity string if supplied
    - req.correlation_id:  best-effort correlation id
    - context.*:           flattened context dict (if 'context' present)
    """
    attrs: Dict[str, Any] = {}

    service_ident = _coerce_service_identity_from_ctx(ctx)
    if service_ident:
        attrs["simcore.identity.service"] = service_ident

    codec_id = ctx.get("codec")
    if codec_id:
        attrs["simcore.identity.codec"] = codec_id

    corr = (
            ctx.get("correlation_id")
            or ctx.get("req_correlation_id")
            or ctx.get("request_correlation_id")
    )
    if corr:
        attrs["req.correlation_id"] = corr

    # Prefer nested `context` for structured span fields
    nested_ctx = ctx.get("context", {})
    if isinstance(nested_ctx, Mapping):
        attrs.update(flatten_context_attrs(nested_ctx))

    return attrs


# -------------------- Backend auto-registration --------------------

# Eagerly ensure common backends are registered on import (best-effort)
# NOTE: Keep these guarded so projects without Celery don't crash.

try:
    # Inline/immediate backend
    # Register under canonical key "immediate" regardless of class name.
    from .inline_backend import InlineBackend  # noqa: F401

    register_backend("immediate", InlineBackend)
except Exception:
    pass

try:
    # Celery backend (optional)
    from .celery_backend import CeleryBackend  # noqa: F401

    register_backend("celery", CeleryBackend)
except Exception:
    pass
