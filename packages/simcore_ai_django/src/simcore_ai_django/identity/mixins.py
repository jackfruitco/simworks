# packages/simcore_ai_django/src/simcore_ai_django/identity/mixins.py
from __future__ import annotations

import logging

from simcore_ai.identity.mixins import IdentityMixin
from simcore_ai_django.identity.resolution import resolve_identity_django

logger = logging.getLogger(__name__)


class DjangoIdentityMixin(IdentityMixin):
    """
    Django-aware identity mixin providing read-only access to derived identities.

    This mixin does not mutate or set identity fields on the class.
    Instead, it delegates to the `DjangoIdentityResolver` to *compute*
    an identity when requested.

    Usage:
        - Define `namespace`, `kind`, and/or `name` as optional class attributes.
        - Call `cls.identity_tuple()` or `cls.identity_str()` to resolve the
          effective identity using Django-aware rules.

    Resolution precedence (handled by the resolver):
        * namespace → decorator arg → class attr → AppConfig.label → module root → "default"
        * kind      → decorator arg → class attr → "default"
        * name      → explicit preserved, otherwise derived from class name
                      with segment-aware stripping (core + Django tokens)
    """

    @classmethod
    def identity_tuple(cls) -> tuple[str, str, str]:
        # Feed whatever the class already exposes and let the resolver apply
        # precedence, token stripping, and normalization consistently.
        ns_attr = getattr(cls, "namespace", None)
        kd_attr = getattr(cls, "kind", None)
        nm_attr = getattr(cls, "name", None)

        identity, _meta = resolve_identity_django(
            cls,
            namespace=ns_attr,
            kind=kd_attr,
            name=nm_attr,
        )
        return identity.as_tuple3

    @classmethod
    def identity_str(cls) -> str:
        ns, kd, nm = cls.identity_tuple()
        return f"{ns}.{kd}.{nm}"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip deriving identity for mixins or classes explicitly marked abstract on themselves.
        # IMPORTANT: treat __identity_abstract__ as NON-INHERITING by consulting cls.__dict__ only.
        if (
                cls.__name__.endswith("Mixin")
                or cls.__module__.endswith(".mixins")
                or cls.__dict__.get("__identity_abstract__", False)
        ):
            return

        # Do NOT stamp namespace/kind/name here. Let decorators/resolvers derive at registration time to avoid making 'name' look explicit.
