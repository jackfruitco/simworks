# simcore_ai_django/execution/helpers.py
from __future__ import annotations

"""
Helpers for execution entrypoint:
  - settings accessors
  - tracing attribute extraction
  - backend lookup (re-export from registry)
"""

from collections.abc import Mapping
from typing import Any, Dict, Optional

from django.conf import settings

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
    return getattr(settings, "SIMCORE_AI_EXECUTION", {}) or {}

def settings_default_backend() -> str:
    return str(get_settings_dict().get("DEFAULT_BACKEND", "immediate")).strip().lower()

def settings_default_mode() -> str:
    return str(get_settings_dict().get("DEFAULT_MODE", "sync")).strip().lower()

def settings_default_queue_name() -> Optional[str]:
    backends = get_settings_dict().get("BACKENDS", {}) or {}
    celery_cfg = backends.get("celery", {}) or {}
    q = celery_cfg.get("queue_default")
    return str(q).strip() if q else None


# -------------------- Tracing attribute helper --------------------

def span_attrs_from_ctx(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    ns = ctx.get("namespace")
    kind = ctx.get("kind") or ctx.get("service_bucket")
    name = ctx.get("name") or ctx.get("service_name")
    codec_id = ctx.get("codec_identity")
    corr = ctx.get("correlation_id") or ctx.get("req_correlation_id") or ctx.get("request_correlation_id")
    attrs: Dict[str, Any] = {}
    if ns or kind or name:
        attrs["ai.identity.service"] = ".".join(x for x in (ns, kind, name) if x)
    if codec_id:
        attrs["ai.identity.codec"] = codec_id
    if corr:
        attrs["req.correlation_id"] = corr
    attrs.update(flatten_context_attrs(ctx.get("context", {})))
    return attrs


# Eagerly ensure common backends are registered on import (best-effort)
try:
    from .inline_backend import InlineBackend  # noqa: F401

    register_backend("immediate", InlineBackend)
except Exception:
    pass
try:
    from .celery_backend import CeleryBackend  # noqa: F401

    register_backend("celery", CeleryBackend)
except Exception:
    pass
