# packages/orchestrai_django/src/orchestrai_django/identity/mixins.py


"""
Django-aware identity mixin.

This mixin simply selects the Django resolver for identity derivation and then
inherits all behavior from the core `IdentityMixin` (lazy, class-level cached
resolution; read-only instance property; class helpers for tuple/string forms).

Compatibility helpers `identity_tuple()` and `identity_str()` are kept as thin
wrappers that delegate to the new unified API on `IdentityMixin`.
"""

from orchestrai.identity.mixins import IdentityMixin
from orchestrai_django.identity.resolvers import DjangoIdentityResolver


class DjangoIdentityMixin(IdentityMixin):
    """Django-aware identity mixin providing read-only access to derived identities.

    Behavior is identical to `IdentityMixin` except it uses `DjangoIdentityResolver`
    to infer namespace (preferring AppConfig.label when not explicitly provided)
    and to collect Django-specific strip tokens during name derivation. Class hints
    `domain`, `namespace`, `group`, and `name` remain optional and are consumed
    by the resolver according to precedence rules (no legacy ``kind`` fallback).
    """

    # Use the Django resolver for all subclasses that include this mixin
    identity_resolver_cls = DjangoIdentityResolver

    @classmethod
    def resolve_identity(cls) -> "Identity":
        """Resolve and cache identity using the Django resolver without `kind` fallback."""
        cached = cls._IdentityMixin__identity_cached  # type: ignore[attr-defined]
        if cached is not None:
            return cached

        from orchestrai_django.identity.resolvers import resolve_identity_django

        with cls._IdentityMixin__identity_lock:  # type: ignore[attr-defined]
            if cls._IdentityMixin__identity_cached is not None:  # type: ignore[attr-defined]
                return cls._IdentityMixin__identity_cached  # type: ignore[attr-defined]

            hints = dict(
                domain=getattr(cls, "domain", None),
                namespace=getattr(cls, "namespace", None),
                group=getattr(cls, "group", None),
                name=getattr(cls, "name", None),
            )
            ident, meta = resolve_identity_django(cls, **hints, context=None)
            cls._IdentityMixin__identity_cached = ident  # type: ignore[attr-defined]
            cls._IdentityMixin__identity_meta_cached = dict(meta or {})  # type: ignore[attr-defined]
            return ident

__all__ = ["DjangoIdentityMixin"]
