# simcore_ai/identity/__init__.py
"""Public identity API (core).

This package exposes the *dumb* Identity dataclass, the public resolver helper,
and selected low-level utilities. Identity derivation is centralized in
`simcore_ai.identity.resolution.IdentityResolver`.

Exports intentionally avoid wildcard imports to keep the surface explicit.
"""
from __future__ import annotations

from .base import Identity, IdentityKey
from .resolvers import resolve_identity  # convenience helper (uses IdentityResolver)
from .registry_resolvers import try_resolve_from_ident
from .utils import (
    DEFAULT_IDENTITY_STRIP_TOKENS,
    strip_tokens,
    snake,
    module_root,
    resolve_collision,
    parse_dot_identity,
    coerce_identity_key,
)

# Optional: keep IdentityMixin export if available in this package.
try:  # pragma: no cover - optional convenience export
    from .mixins import IdentityMixin  # type: ignore
except Exception:  # pragma: no cover
    IdentityMixin = None  # sentinel for projects not using core mixins

__all__ = [
    "Identity",
    "IdentityKey",
    "resolve_identity",
    "DEFAULT_IDENTITY_STRIP_TOKENS",
    "strip_tokens",
    "snake",
    "module_root",
    "resolve_collision",
    "parse_dot_identity",
    "coerce_identity_key",
    "try_resolve_from_ident"
]

# Only expose IdentityMixin if it exists locally.
if IdentityMixin is not None:  # pragma: no cover
    __all__.append("IdentityMixin")
