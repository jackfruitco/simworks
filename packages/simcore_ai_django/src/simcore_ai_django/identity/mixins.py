# packages/simcore_ai_django/src/simcore_ai_django/identity/mixins.py


"""
Django-aware identity mixin.

This mixin simply selects the Django resolver for identity derivation and then
inherits all behavior from the core `IdentityMixin` (lazy, class-level cached
resolution; read-only instance property; class helpers for tuple/string forms).

Compatibility helpers `identity_tuple()` and `identity_str()` are kept as thin
wrappers that delegate to the new unified API on `IdentityMixin`.
"""

from simcore_ai.identity.mixins import IdentityMixin
from simcore_ai_django.identity.resolvers import DjangoIdentityResolver


class DjangoIdentityMixin(IdentityMixin):
    """Django-aware identity mixin providing read-only access to derived identities.

    Behavior is identical to `IdentityMixin` except it uses `DjangoIdentityResolver`
    to infer namespace (preferring AppConfig.label when not explicitly provided)
    and to collect Django-specific strip tokens during name derivation.

    Class hints `namespace`, `kind`, and `name` remain optional and are consumed
    by the resolver according to precedence rules.
    """

    # Use the Django resolver for all subclasses that include this mixin
    identity_resolver_cls = DjangoIdentityResolver

__all__ = ["DjangoIdentityMixin"]
